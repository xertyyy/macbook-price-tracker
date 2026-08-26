"""
Orchestrierung: fuer jedes getrackte Produkt scrapen -> KI-bewerten ->
in der Datenbank speichern -> nur NEUE Angebote an Discord senden.

Produkte kommen ab jetzt aus Supabase (geteilte, serverweite Liste) statt
aus einem hartcodierten Literal. Ist die Datenbank leer (allererster Lauf),
wird automatisch ein Standard-Produkt (MacBook) angelegt, damit der Tracker
sofort weiterlaeuft, ohne dass von Hand ein Eintrag erstellt werden muss.
"""
import os
import random
import sys
import time
from datetime import datetime, timedelta, timezone

from tracker.ai import apply_offer_ratings
from tracker.config import MAX_OFFERS_TO_SHOW, STARTUP_JITTER_RANGE, TIER_RANK
from tracker.embeds import build_checkin_message, build_offer_messages, count_by_source, send_discord_message
from tracker.models import Product
from tracker.scrapers import collect_offers_for_product
from tracker.store import Store

# Stunde (UTC), in der einmal taeglich eine Check-in-Nachricht mit
# Dashboard-Link gesendet wird — unabhaengig davon, ob neue Angebote
# gefunden wurden. Nur EIN Cron-Tick pro Tag matcht (siehe
# _should_send_daily_checkin): der jeweils erste Lauf nach dieser Uhrzeit.
DAILY_CHECKIN_HOUR_UTC = 9

# Vorlage fuer das allererste, automatisch angelegte Produkt (siehe
# _seed_default_product). Danach kommen weitere Produkte per /track dazu.
DEFAULT_PRODUCT = Product(
    name="MacBook Pro 14 M3 Pro 18GB 512GB",
    queries=[
        "MacBook Pro 14 M3 Pro 18GB 512GB",
        "MacBook Pro 14 M3 Pro",
        "MacBook Pro 14 Zoll M3 Pro",
        "Apple MacBook Pro 14 2023 M3 Pro",
        "MacBook Pro M3 Pro 14 Zoll 18 512",
    ],
    required_keywords=["macbook", "m3"],
    exclude_keywords=["8gb", "16gb", "36gb", "8 gb", "16 gb", "36 gb"],
    min_price=500.0,
)

# Wie lange run_all() hoechstens scrapen darf, bevor es fuer diesen Lauf
# abbricht (Rest kommt beim naechsten Cron-Durchlauf dran). Laesst Puffer
# im 30-Minuten-Fenster fuer Setup/Checkout/pip install.
DEFAULT_BUDGET_SECONDS = 1500

# Wie viele Produkte pro Lauf hoechstens bearbeitet werden (Budgeted-Round-
# Robin: die am laengsten nicht gescrapten zuerst).
DEFAULT_PRODUCT_LIMIT = 12

# Clock-Skew-Toleranz beim Erkennen "neuer" Angebote (first_seen_at vs.
# Laufstart) — verhindert, dass ein Angebot faelschlich als "schon bekannt"
# gilt, nur weil unsere Uhr ein paar Sekunden vor/nach der DB-Uhr liegt.
NEW_OFFER_CLOCK_SKEW = timedelta(seconds=5)


def _seed_default_product(store):
    print("Keine Produkte in der Datenbank — lege Standard-Produkt an.")
    product = store.add_product(DEFAULT_PRODUCT.name)
    store.set_product_config(
        product.id,
        queries=DEFAULT_PRODUCT.queries,
        required_keywords=DEFAULT_PRODUCT.required_keywords,
        exclude_keywords=DEFAULT_PRODUCT.exclude_keywords,
        min_price=DEFAULT_PRODUCT.min_price,
        status="ready",
    )


def _should_send_daily_checkin(run_started_at):
    """Feuert nur beim ersten Cron-Tick der Stunde DAILY_CHECKIN_HOUR_UTC
    (Minute < 5 faengt den :00-Tick samt Start-Jitter ab, schliesst den
    :30-Tick derselben Stunde aber aus) — dadurch genau einmal pro Tag.
    Nimmt den Zeitpunkt vom LAUFSTART entgegen (nicht neu abgefragt), da das
    Scraping selbst mehrere Minuten dauern kann und das 5-Minuten-Fenster
    sonst laengst vorbei waere."""
    return run_started_at.hour == DAILY_CHECKIN_HOUR_UTC and run_started_at.minute < 5


def _send_daily_checkin(store, webhook_url):
    products = store.list_products(active_only=True)
    if not products:
        return
    summaries = []
    for product in products:
        current = store.current_offers(product.id, limit=100)
        best = current[0] if current else None
        summaries.append((product.name, best, count_by_source(current)))
    print(f"Sende taegliche Check-in-Nachricht fuer {len(summaries)} Produkt(e).")
    send_discord_message(build_checkin_message(summaries), webhook_url)


def _is_new_offer(row, run_started):
    first_seen = row.get("first_seen_at")
    if not first_seen:
        return True
    try:
        first_seen_dt = datetime.fromisoformat(first_seen.replace("Z", "+00:00"))
    except ValueError:
        return True
    return first_seen_dt >= run_started - NEW_OFFER_CLOCK_SKEW


def run_for_product(product, store, webhook_url, gemini_api_key, *, push_all=False):
    """Ein voller Durchlauf fuer EIN Produkt: scrapen, bewerten, speichern,
    nur neue (oder bei push_all=True alle passenden) Angebote senden."""
    run_started = datetime.now(timezone.utc)
    run_id = store.start_run(product.id)

    try:
        offers = collect_offers_for_product(product)
    except Exception as exc:
        print(f"Scraping fehlgeschlagen: {exc}", file=sys.stderr)
        store.finish_run(run_id, status="error", error=str(exc))
        store.touch_product(product.id, run_id=run_id, ok=False)
        return

    if not offers:
        print("Keine (funktionsfaehigen) Angebote gefunden.")
        store.finish_run(run_id, status="no_results", offers_found=0, offers_kept=0, offers_new=0)
        store.touch_product(product.id, run_id=run_id, ok=True)
        return

    kept, market_info = apply_offer_ratings(offers, product.name, gemini_api_key)

    stats_body = {"offers_found": len(offers), "offers_kept": len(kept)}
    if market_info and market_info.get("geschaetzter_marktpreis"):
        stats_body["ai_market_estimate"] = market_info["geschaetzter_marktpreis"]
        if market_info.get("begruendung"):
            stats_body["ai_market_note"] = market_info["begruendung"]

    if not kept:
        print("Keine Angebote nach KI-Bewertung/Preisfilter uebrig.")
        store.finish_run(run_id, status="ok", offers_new=0, **stats_body)
        store.touch_product(product.id, run_id=run_id, ok=True)
        return

    kept.sort(key=lambda o: (TIER_RANK.get(o["tier"], 99), o["price"]))

    rows = store.upsert_offers(product.id, run_id, kept)
    store.record_price_points(product.id, run_id, kept)

    rows_by_link = {r["link"]: r for r in rows}
    if push_all:
        to_send = kept
    else:
        to_send = [o for o in kept if _is_new_offer(rows_by_link.get(o["link"], {}), run_started)]

    store.finish_run(run_id, status="ok", offers_new=len(to_send), **stats_body)
    store.touch_product(product.id, run_id=run_id, ok=True)

    if not to_send:
        print(f"{len(kept)} passende Angebote, aber 0 davon neu — keine Discord-Nachricht.")
        return

    shown = to_send[:MAX_OFFERS_TO_SHOW]
    if len(to_send) > MAX_OFFERS_TO_SHOW:
        print(f"HINWEIS: {len(to_send) - MAX_OFFERS_TO_SHOW} weitere neue Angebote werden wegen MAX_OFFERS_TO_SHOW nicht gesendet.")

    print(f"{len(shown)} von {len(to_send)} neuen Angeboten werden an Discord gesendet.")
    for offer in shown:
        print(f" - [{offer['tier']}] {offer['title']} — {offer['price']:.2f} € ({offer['source']})")

    payloads, _ = build_offer_messages(product.name, shown, market_info, source_counts=count_by_source(kept))
    print(f"Sende {len(payloads)} Discord-Nachricht(en) fuer {len(shown)} Angebote.")
    for idx, payload in enumerate(payloads):
        send_discord_message(payload, webhook_url)
        if idx < len(payloads) - 1:
            time.sleep(1.5)


def run_all(webhook_url, gemini_api_key, *, budget_seconds=DEFAULT_BUDGET_SECONDS, limit=DEFAULT_PRODUCT_LIMIT):
    run_started_at = datetime.now(timezone.utc)
    store = Store()

    if not store.list_products(active_only=False):
        _seed_default_product(store)

    products = store.products_due(limit=limit)
    if not products:
        print("Keine aktiven Produkte in der Datenbank.")
    else:
        started_at = time.monotonic()
        for product in products:
            if time.monotonic() - started_at > budget_seconds:
                print("Zeitbudget fuer diesen Lauf aufgebraucht — Rest folgt beim naechsten Mal.")
                break
            print(f"=== Produkt: {product.name} ===")
            run_for_product(product, store, webhook_url, gemini_api_key)

    if _should_send_daily_checkin(run_started_at):
        _send_daily_checkin(store, webhook_url)


def main():
    webhook_url = os.getenv("DISCORD_WEBHOOK_URL")
    if not webhook_url:
        print("FEHLER: DISCORD_WEBHOOK_URL nicht gesetzt.", file=sys.stderr)
        sys.exit(1)

    if not os.getenv("SUPABASE_URL") or not os.getenv("SUPABASE_SERVICE_KEY"):
        print("FEHLER: SUPABASE_URL/SUPABASE_SERVICE_KEY nicht gesetzt.", file=sys.stderr)
        sys.exit(1)

    gemini_api_key = os.getenv("GEMINI_API_KEY")

    startup_delay = random.uniform(*STARTUP_JITTER_RANGE)
    print(f"Warte {startup_delay:.1f}s (Start-Jitter) vor der ersten Anfrage...")
    time.sleep(startup_delay)

    run_all(webhook_url, gemini_api_key)


if __name__ == "__main__":
    main()
