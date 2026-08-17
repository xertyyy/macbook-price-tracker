"""
Orchestrierung: fuer jedes getrackte Produkt scrapen -> KI-bewerten ->
an Discord senden.

M0-Stand: Produktliste ist ein hartcodiertes Literal (MACBOOK_PRODUCT). Ab
M1 kommt die Liste aus einer Datenbank (mehrere Produkte, serverweit geteilt,
per Discord-Bot verwaltet) — run_for_product() aendert sich dafuer nicht.
"""
import os
import random
import sys
import time

from tracker.ai import apply_offer_ratings
from tracker.config import MAX_OFFERS_TO_SHOW, STARTUP_JITTER_RANGE, TIER_RANK
from tracker.embeds import build_offer_messages, send_discord_message
from tracker.models import Product
from tracker.scrapers import collect_offers_for_product

# TODO(M1): aus der Datenbank laden statt hartcodiert.
MACBOOK_PRODUCT = Product(
    name="MacBook Pro 14 M2 Pro 16GB 512GB",
    queries=[
        "MacBook Pro 14 M2 Pro 16GB 512GB",
        "MacBook Pro 14 M2 Pro",
        "MacBook Pro 14 Zoll M2 Pro",
        "Apple MacBook Pro 14 2023 M2 Pro",
        "MacBook Pro M2 Pro 14 Zoll 16 512",
    ],
    required_keywords=["macbook"],
    min_price=400.0,
)


def run_for_product(product, webhook_url, gemini_api_key):
    offers = collect_offers_for_product(product)
    if not offers:
        print("Keine (funktionsfaehigen) Angebote gefunden.")
        return

    kept, market_info = apply_offer_ratings(offers, product.name, gemini_api_key)
    if not kept:
        print("Keine Angebote nach KI-Bewertung/Preisfilter uebrig — es wird nichts gesendet.")
        return

    kept.sort(key=lambda o: (TIER_RANK.get(o["tier"], 99), o["price"]))
    shown = kept[:MAX_OFFERS_TO_SHOW]
    if len(kept) > MAX_OFFERS_TO_SHOW:
        print(f"HINWEIS: {len(kept) - MAX_OFFERS_TO_SHOW} weitere gute Angebote werden wegen MAX_OFFERS_TO_SHOW nicht gesendet.")

    print(f"{len(shown)} von {len(kept)} passenden Angeboten werden an Discord gesendet.")
    for offer in shown:
        print(f" - [{offer['tier']}] {offer['title']} — {offer['price']:.2f} € ({offer['source']})")

    payloads, _ = build_offer_messages(product.name, shown, market_info)
    print(f"Sende {len(payloads)} Discord-Nachricht(en) fuer {len(shown)} Angebote.")
    for idx, payload in enumerate(payloads):
        send_discord_message(payload, webhook_url)
        if idx < len(payloads) - 1:
            time.sleep(1.5)


def main():
    webhook_url = os.getenv("DISCORD_WEBHOOK_URL")
    if not webhook_url:
        print("FEHLER: DISCORD_WEBHOOK_URL nicht gesetzt.", file=sys.stderr)
        sys.exit(1)

    gemini_api_key = os.getenv("GEMINI_API_KEY")

    startup_delay = random.uniform(*STARTUP_JITTER_RANGE)
    print(f"Warte {startup_delay:.1f}s (Start-Jitter) vor der ersten Anfrage...")
    time.sleep(startup_delay)

    products = [MACBOOK_PRODUCT]
    for product in products:
        print(f"=== Produkt: {product.name} ===")
        run_for_product(product, webhook_url, gemini_api_key)


if __name__ == "__main__":
    main()
