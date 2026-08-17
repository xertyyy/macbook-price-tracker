"""
Preis-Tracker fuer MacBook Pro 14 M2 Pro (16GB RAM, 512GB SSD)
Quellen: Kleinanzeigen.de, eBay.de, Back Market, refurbed
KI-Zustandsbewertung optional ueber die kostenlose Google-Gemini-API
"""
import json
import os
import random
import re
import sys
import time
from datetime import datetime, timezone
from urllib.parse import quote_plus
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# KONFIGURATION — hier kannst du Werte anpassen
# ---------------------------------------------------------------------------
# Realistischer Marktvergleich (Stand 2026): ein professionell aufbereitetes
# Refurbished-Geraet dieses Modells mit Garantie kostet bei Haendlern derzeit
# ca. 1.300-1.400 €. Alles deutlich darunter ist ein echtes Schnaeppchen,
# alles in der Naehe ein fairer Preis, alles druemer ist im Vergleich zu teuer
# und wird NICHT an Discord gemeldet.
PRICE_THRESHOLD_BARGAIN = 950.0    # unter diesem Preis: GRUEN + @everyone-Ping (Schnaeppchen)
PRICE_THRESHOLD_GOOD    = 1250.0   # bis hier: ORANGE (guter/fairer Preis) — darueber: wird ignoriert

COLOR_GREEN  = 0x00FF00
COLOR_ORANGE = 0xFFA500
COLOR_RED    = 0xFF0000

# Google-Gemini-Modelle fuer die KOSTENLOSE KI-Zustandsbewertung der Angebote
# (Free-Tier ueber Google AI Studio, siehe README). Google stellt Modelle
# regelmaessig ab (z. B. wurde gemini-2.0-flash am 1.6.2026 abgeschaltet) —
# deshalb wird der Reihe nach durchprobiert. Erstes verfuegbares Modell
# gewinnt. Falls irgendwann ALLE hier 404 liefern: auf ai.google.dev/gemini-api/docs/models
# nachschauen, welche Modelle aktuell im Free-Tier verfuegbar sind, und
# diese Liste aktualisieren.
GEMINI_MODEL_CANDIDATES = [
    "gemini-2.5-flash-lite",
    "gemini-2.5-flash",
    "gemini-flash-latest",
]

# Reihenfolge/Sortierung und Emoji je Qualitaetsstufe. "Schnaeppchen" und
# "Guter Preis" sind die Ersatz-Stufen, falls kein GEMINI_API_KEY gesetzt
# ist bzw. die KI-Analyse fehlschlaegt (dann wird rein nach Preis bewertet).
TIER_RANK = {
    "Top-Deal": 0,
    "Schnaeppchen": 0,
    "Gut": 1,
    "Guter Preis": 1,
    "Okay": 2,
    "Vorsicht": 3,
    "Unbewertet": 4,
}
TIER_EMOJI = {
    "Top-Deal": "🟢",
    "Schnaeppchen": "🟢",
    "Gut": "🟡",
    "Guter Preis": "🟡",
    "Okay": "🟠",
    "Vorsicht": "🔴",
    "Unbewertet": "⚪",
}

# Verschiedene Suchbegriff-Varianten, weil Verkaeufer das Modell
# unterschiedlich betiteln. Jede Quelle wird mit JEDER Variante
# durchsucht, damit moeglichst kein Angebot uebersehen wird.
# Hier kannst du weitere Varianten ergaenzen oder entfernen.
SEARCH_QUERIES = [
    "MacBook Pro 14 M2 Pro 16GB 512GB",
    "MacBook Pro 14 M2 Pro",
    "MacBook Pro 14 Zoll M2 Pro",
    "Apple MacBook Pro 14 2023 M2 Pro",
    "MacBook Pro M2 Pro 14 Zoll 16 512",
]

# Woerter im Titel, bei denen ein Angebot als defekt/beschaedigt gilt und
# NICHT gemeldet wird. Hier kannst du weitere Begriffe ergaenzen.
BROKEN_KEYWORDS = [
    "wackelkontakt",
    "defekt",
    "kaputt",
    "riss",
    "gesprungen",
    "beschaedigt",
    "beschädigt",
    "bastler",
    "ersatzteil",
    "nicht funktionsfaehig",
    "nicht funktionsfähig",
    "wasserschaden",
    "fehler",
    "schaden",
    "ohne funktion",
    "als ersatzteillager",
    "battery issue",
    "akku defekt",
    "display defekt",
    "displayschaden",
    "displayfehler",
    "bootet nicht",
    "startet nicht",
    "geht nicht an",
    "biete zum ausschlachten",
]


def is_broken(title):
    """Prueft, ob ein Angebotstitel auf ein defektes/beschaedigtes Geraet hindeutet."""
    lowered = title.lower()
    return any(keyword in lowered for keyword in BROKEN_KEYWORDS)


# Mehrere realistische, aktuelle Browser-User-Agents — bei jedem Lauf wird
# zufaellig einer gewaehlt, damit nicht jede Anfrage exakt gleich aussieht.
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:126.0) Gecko/20100101 Firefox/126.0",
]

HEADERS = {
    "User-Agent": random.choice(USER_AGENTS),
    "Accept-Language": "de-DE,de;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}
REQUEST_TIMEOUT = 15

# Verzoegerung zwischen den Anfragen an die einzelnen Marktplaetze (Sekunden).
# Zufaelliger Wert in diesem Bereich, damit die Anfragen nicht wie ein
# starres Skript im Sekundentakt aussehen.
SITE_DELAY_RANGE = (4, 12)

# Zufaellige Startverzoegerung (Sekunden), bevor ueberhaupt die erste Anfrage
# rausgeht. Verhindert, dass Anfragen exakt zur vollen/halben Stunde kommen.
STARTUP_JITTER_RANGE = (0, 90)

def _kleinanzeigen_slug(query):
    """Wandelt einen Suchbegriff in das Kleinanzeigen-URL-Format (a-b-c) um."""
    slug = re.sub(r"[^a-z0-9]+", "-", query.lower()).strip("-")
    return slug

# ---------------------------------------------------------------------------
# SCRAPER: Kleinanzeigen.de
# ---------------------------------------------------------------------------
def scrape_kleinanzeigen(query):
    results = []
    url = f"https://www.kleinanzeigen.de/s-{_kleinanzeigen_slug(query)}/k0"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
    except requests.RequestException as exc:
        print(f"[Kleinanzeigen] Fehler: {exc}", file=sys.stderr)
        return results

    soup = BeautifulSoup(resp.text, "lxml")
    for card in soup.select("article.aditem"):
        title_el = card.select_one(".ellipsis, h2")
        price_el = card.select_one(".aditem-main--middle--price-shipping--price")
        link_el  = card.select_one("a[href]")
        if not (title_el and price_el and link_el):
            continue
        title = title_el.get_text(strip=True)
        price = _parse_price(price_el.get_text(strip=True))
        href  = link_el.get("href", "")
        if price is None or price < 400 or "macbook" not in title.lower():
            continue
        if is_broken(title):
            continue
        link = href if href.startswith("http") else f"https://www.kleinanzeigen.de{href}"
        img  = card.select_one("img")
        results.append({
            "source": "Kleinanzeigen.de",
            "title": title,
            "price": price,
            "link":  link,
            "image": img.get("src") if img else None,
        })
    return results

# ---------------------------------------------------------------------------
# SCRAPER: eBay.de
# ---------------------------------------------------------------------------
def scrape_ebay(query):
    results = []
    url = (
        "https://www.ebay.de/sch/i.html"
        f"?_nkw={quote_plus(query)}"
        "&LH_ItemCondition=3000"
        "&_sacat=0"
    )
    try:
        resp = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
    except requests.RequestException as exc:
        print(f"[eBay] Fehler: {exc}", file=sys.stderr)
        return results

    soup = BeautifulSoup(resp.text, "lxml")
    for card in soup.select(".s-item"):
        title_el = card.select_one(".s-item__title")
        price_el = card.select_one(".s-item__price")
        link_el  = card.select_one("a.s-item__link")
        if not (title_el and price_el and link_el):
            continue
        title = title_el.get_text(strip=True)
        price = _parse_price(price_el.get_text(strip=True))
        link  = link_el.get("href", "")
        if price is None or price < 400 or "macbook" not in title.lower():
            continue
        if is_broken(title):
            continue
        img = card.select_one("img")
        results.append({
            "source": "eBay.de",
            "title": title,
            "price": price,
            "link":  link,
            "image": img.get("src") if img else None,
        })
    return results

# ---------------------------------------------------------------------------
# SCRAPER: Back Market (refurbished)
# ---------------------------------------------------------------------------
def scrape_back_market(query):
    results = []
    url = f"https://www.backmarket.de/de-de/search?q={quote_plus(query)}"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
    except requests.RequestException as exc:
        print(f"[Back Market] Fehler: {exc}", file=sys.stderr)
        return results

    soup = BeautifulSoup(resp.text, "lxml")
    cards = soup.select("[data-qa='productCard'], article")

    for card in cards:
        title_el = card.select_one("[data-qa='productCardTitle'], h2, h3")
        price_el = card.select_one("[data-qa='productCardPrice'], [class*='price']")
        link_el  = card.select_one("a[href]")
        if not (title_el and price_el and link_el):
            continue
        title = title_el.get_text(strip=True)
        price = _parse_price(price_el.get_text(strip=True))
        href  = link_el.get("href", "")
        if price is None or price < 400 or "macbook" not in title.lower():
            continue
        if is_broken(title):
            continue
        link = href if href.startswith("http") else f"https://www.backmarket.de{href}"
        img  = card.select_one("img")
        results.append({
            "source": "Back Market",
            "title": title,
            "price": price,
            "link":  link,
            "image": img.get("src") if img else None,
        })
    return results

# ---------------------------------------------------------------------------
# SCRAPER: refurbed (refurbished)
# ---------------------------------------------------------------------------
def scrape_refurbed(query):
    results = []
    url = f"https://www.refurbed.de/search?q={quote_plus(query)}"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
    except requests.RequestException as exc:
        print(f"[refurbed] Fehler: {exc}", file=sys.stderr)
        return results

    soup = BeautifulSoup(resp.text, "lxml")
    cards = soup.select("a[href*='/p/']")

    for card in cards:
        title_el = card.select_one("[class*='title'], h2, h3")
        price_el = card.select_one("[class*='price']")
        if not (title_el and price_el):
            continue
        title = title_el.get_text(strip=True)
        price = _parse_price(price_el.get_text(strip=True))
        href  = card.get("href", "")
        if price is None or price < 400 or "macbook" not in title.lower():
            continue
        if is_broken(title):
            continue
        link = href if href.startswith("http") else f"https://www.refurbed.de{href}"
        img  = card.select_one("img")
        results.append({
            "source": "refurbed",
            "title": title,
            "price": price,
            "link":  link,
            "image": img.get("src") if img else None,
        })
    return results

# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------
def _parse_price(raw):
    if not raw:
        return None
    cleaned = re.sub(r"[^\d,.]", "", raw).replace(".", "").replace(",", ".")
    m = re.search(r"\d+(\.\d+)?", cleaned)
    try:
        return float(m.group()) if m else None
    except ValueError:
        return None

def _dedupe_offers(offers):
    """Entfernt doppelte Treffer (gleicher Link), die durch mehrere
    Suchanfrage-Varianten mehrfach gefunden wurden."""
    seen = set()
    deduped = []
    for offer in offers:
        if offer["link"] in seen:
            continue
        seen.add(offer["link"])
        deduped.append(offer)
    return deduped

def collect_all_offers():
    offers = []
    scrapers = [scrape_kleinanzeigen, scrape_ebay, scrape_back_market, scrape_refurbed]
    tasks = [(scraper, query) for scraper in scrapers for query in SEARCH_QUERIES]

    for index, (scraper, query) in enumerate(tasks):
        try:
            found = scraper(query)
            print(f"{scraper.__name__} ('{query}'): {len(found)} Treffer")
            offers.extend(found)
        except Exception as exc:
            print(f"{scraper.__name__} ('{query}') Fehler: {exc}", file=sys.stderr)
        if index < len(tasks) - 1:
            delay = random.uniform(*SITE_DELAY_RANGE)
            time.sleep(delay)

    deduped = _dedupe_offers(offers)
    print(f"{len(offers)} Rohtreffer, {len(deduped)} nach Entfernen von Duplikaten.")
    return deduped

# ---------------------------------------------------------------------------
# KI-Zustandsbewertung (Google Gemini API, kostenloser Free-Tier)
# ---------------------------------------------------------------------------
GEMINI_RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "ratings": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "index": {"type": "INTEGER"},
                    "tier": {
                        "type": "STRING",
                        "enum": ["Top-Deal", "Gut", "Okay", "Vorsicht"],
                    },
                    "begruendung": {"type": "STRING"},
                },
                "required": ["index", "tier", "begruendung"],
            },
        }
    },
    "required": ["ratings"],
}

def classify_price_fallback(price):
    """Einfache Preis-Einstufung ohne KI (Fallback, falls kein
    GEMINI_API_KEY gesetzt ist oder die KI-Analyse fehlschlaegt)."""
    return "Schnaeppchen" if price < PRICE_THRESHOLD_BARGAIN else "Guter Preis"

def analyze_offers_with_ai(offers, api_key):
    """Laesst Gemini jedes Angebot anhand von Titel/Preis/Quelle in eine
    Qualitaetsstufe einordnen und gibt eine Liste von
    {index, tier, begruendung} zurueck."""
    listing_lines = "\n".join(
        f"{i}. Titel: \"{offer['title']}\" | Preis: {offer['price']:.2f} EUR | Quelle: {offer['source']}"
        for i, offer in enumerate(offers)
    )

    prompt = (
        "Du bewertest gebrauchte/refurbished MacBook Pro 14 M2 Pro (16GB/512GB) "
        "Angebote fuer einen persoenlichen Preis-Tracker. Ein professionell "
        "aufbereitetes Refurbished-Geraet mit Garantie kostet am Markt aktuell "
        "ca. 1.300-1.400 EUR.\n\n"
        "Ordne JEDES der folgenden Angebote anhand von Titel, Preis und Quelle in "
        "genau eine Stufe ein:\n"
        "- 'Top-Deal': sehr guter Zustand/Ausstattung laut Titel UND deutlich unter Marktpreis\n"
        "- 'Gut': guter Preis, Zustand wirkt laut Titel in Ordnung\n"
        "- 'Okay': fairer Preis, aber wenig Info zu Zustand/Ausstattung im Titel\n"
        "- 'Vorsicht': Titel wirkt vage, widerspruechlich oder es fehlen wichtige Angaben\n\n"
        f"{listing_lines}\n\n"
        "Gib fuer JEDES Angebot genau einen Eintrag zurueck."
    )

    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseSchema": GEMINI_RESPONSE_SCHEMA,
        },
    }

    last_exc = None
    for model in GEMINI_MODEL_CANDIDATES:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        try:
            resp = requests.post(url, params={"key": api_key}, json=body, timeout=60)
            if resp.status_code == 404:
                # Modell existiert nicht (mehr) fuer diesen Key/diese API-Version — naechstes probieren
                last_exc = requests.HTTPError(f"Modell '{model}' nicht verfuegbar (404)")
                continue
            resp.raise_for_status()
            data = resp.json()
            text = data["candidates"][0]["content"]["parts"][0]["text"]
            return json.loads(text).get("ratings", [])
        except requests.RequestException as exc:
            last_exc = exc
            continue

    raise last_exc or RuntimeError("Kein Gemini-Modell aus GEMINI_MODEL_CANDIDATES verfuegbar")

def apply_offer_ratings(offers, api_key):
    """Versieht jedes Angebot mit 'tier' und 'tier_note'. Nutzt die KI, falls
    ein API-Key vorhanden ist und der Aufruf klappt — sonst die Preis-Einstufung."""
    if not api_key:
        print("GEMINI_API_KEY nicht gesetzt — nutze einfache Preis-Einstufung statt KI-Analyse.")
        for offer in offers:
            offer["tier"] = classify_price_fallback(offer["price"])
            offer["tier_note"] = ""
        return

    try:
        ratings = analyze_offers_with_ai(offers, api_key)
        rating_by_index = {r["index"]: r for r in ratings if isinstance(r, dict) and "index" in r}
        for i, offer in enumerate(offers):
            rating = rating_by_index.get(i)
            if rating and rating.get("tier") in TIER_RANK:
                offer["tier"] = rating["tier"]
                offer["tier_note"] = rating.get("begruendung", "")
            else:
                offer["tier"] = classify_price_fallback(offer["price"])
                offer["tier_note"] = ""
        print(f"KI-Analyse erfolgreich fuer {len(rating_by_index)}/{len(offers)} Angebote.")
    except Exception as exc:
        print(f"KI-Analyse fehlgeschlagen, nutze Preis-Einstufung: {exc}", file=sys.stderr)
        for offer in offers:
            offer["tier"] = classify_price_fallback(offer["price"])
            offer["tier_note"] = ""

# ---------------------------------------------------------------------------
# Discord Webhook
# ---------------------------------------------------------------------------
# Discord-Grenzen: max. 25 Felder pro Embed UND max. 6000 Zeichen insgesamt
# ueber ALLE Embeds einer Nachricht. Wir bleiben bei EINEM Embed pro Nachricht
# und halten uns bewusst unter beiden Grenzen (Sicherheitsmarge), damit lange
# Titel/Links nie zu einem 400-Fehler ("Bad Request") fuehren. Bei mehr
# Angeboten als in eine Nachricht passen, werden mehrere Nachrichten gesendet.
MAX_FIELDS_PER_EMBED = 20
MAX_EMBED_CHARS = 5000
MAX_MESSAGES = 10

def _offer_field(index, offer):
    tier = offer.get("tier", "Unbewertet")
    emoji = TIER_EMOJI.get(tier, "⚪")
    title_short = offer["title"] if len(offer["title"]) <= 70 else offer["title"][:69] + "…"
    return {
        "name": f"{emoji}  {offer['price']:.2f} €  ·  {offer['source']}  ·  {tier}",
        "value": f"[{title_short}]({offer['link']})",
        "inline": False,
    }

def build_offer_messages(offers):
    """Baut eine Liste von Discord-Nachrichten-Payloads (je EIN Embed mit
    anklickbaren Angeboten). Angebote werden nach Zeichen-/Feld-Budget auf
    mehrere Nachrichten aufgeteilt, damit Discords 6000-Zeichen-Limit pro
    Nachricht nie gerissen wird. Die erste Nachricht bekommt ein Vorschaubild."""
    has_top_deal = any(offer.get("tier") in ("Top-Deal", "Schnaeppchen") for offer in offers)
    color = COLOR_GREEN if has_top_deal else COLOR_ORANGE
    now = datetime.now(timezone.utc).isoformat()

    field_chunks = []
    current_fields = []
    current_chars = 0

    for i, offer in enumerate(offers):
        if len(field_chunks) >= MAX_MESSAGES:
            remaining = len(offers) - i
            print(f"HINWEIS: {remaining} weitere Angebote werden aus Nachrichten-Limit-Gruenden nicht gesendet.")
            break
        field = _offer_field(i + 1, offer)
        field_chars = len(field["name"]) + len(field["value"])
        if current_fields and (len(current_fields) >= MAX_FIELDS_PER_EMBED or current_chars + field_chars > MAX_EMBED_CHARS):
            field_chunks.append(current_fields)
            current_fields = []
            current_chars = 0
        current_fields.append(field)
        current_chars += field_chars
    if current_fields:
        field_chunks.append(current_fields)

    total = len(field_chunks)
    payloads = []
    for idx, fields in enumerate(field_chunks):
        embed = {"color": color, "fields": fields}
        embed["title"] = (
            f"MacBook Pro 14 M2 Pro — {len(offers)} Angebote gefunden"
            if total == 1
            else f"MacBook Pro 14 M2 Pro — Teil {idx + 1}/{total} ({len(offers)} Angebote gesamt)"
        )
        if idx == 0:
            embed["timestamp"] = now
            best_image = next(
                (o["image"] for o in offers if o.get("image") and o["image"].startswith("http")),
                None,
            )
            if best_image:
                embed["image"] = {"url": best_image}
        payloads.append({
            "content": "@everyone Top-Deal(s) gefunden!" if (has_top_deal and idx == 0) else "",
            "embeds": [embed],
        })

    return payloads, has_top_deal

def send_discord_message(payload, webhook_url):
    try:
        resp = requests.post(webhook_url, json=payload, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        print("Discord-Nachricht gesendet.")
    except requests.RequestException as exc:
        print(f"Discord-Webhook Fehler: {exc}", file=sys.stderr)
        try:
            print(f"Discord-Antwort: {resp.text}", file=sys.stderr)
        except Exception:
            pass

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    webhook_url = os.getenv("DISCORD_WEBHOOK_URL")
    if not webhook_url:
        print("FEHLER: DISCORD_WEBHOOK_URL nicht gesetzt.", file=sys.stderr)
        sys.exit(1)

    gemini_api_key = os.getenv("GEMINI_API_KEY")

    startup_delay = random.uniform(*STARTUP_JITTER_RANGE)
    print(f"Warte {startup_delay:.1f}s (Start-Jitter) vor der ersten Anfrage...")
    time.sleep(startup_delay)

    offers = collect_all_offers()

    if not offers:
        print("Keine (funktionsfaehigen) Angebote gefunden.")
        return

    # Guenstigstes Angebot zuerst
    offers_sorted = sorted(offers, key=lambda o: o["price"])

    # Nur GRUENE (Schnaeppchen) und ORANGE (guter Preis) Angebote werden gemeldet.
    # Zu teure (ROT) Angebote werden nur in der Konsole geloggt, nicht an Discord gesendet.
    good_offers = [o for o in offers_sorted if o["price"] <= PRICE_THRESHOLD_GOOD]
    too_expensive = [o for o in offers_sorted if o["price"] > PRICE_THRESHOLD_GOOD]

    print(f"{len(offers_sorted)} funktionsfaehige Angebote gefunden.")
    for offer in too_expensive:
        print(f" - UEBERSPRUNGEN (zu teuer): {offer['title']} — {offer['price']:.2f} € ({offer['source']})")

    if not good_offers:
        print("Keine Angebote im gruenen/orangenen Preisbereich — es wird nichts gesendet.")
        return

    apply_offer_ratings(good_offers, gemini_api_key)
    good_offers.sort(key=lambda o: (TIER_RANK.get(o["tier"], 99), o["price"]))

    print(f"{len(good_offers)} gruene/orangene Angebote — sende eine Sammel-Nachricht an Discord.")
    for offer in good_offers:
        print(f" - [{offer['tier']}] {offer['title']} — {offer['price']:.2f} € ({offer['source']})")

    payloads, _ = build_offer_messages(good_offers)
    print(f"Sende {len(payloads)} Discord-Nachricht(en) fuer {len(good_offers)} Angebote.")
    for idx, payload in enumerate(payloads):
        send_discord_message(payload, webhook_url)
        if idx < len(payloads) - 1:
            time.sleep(1.5)

if __name__ == "__main__":
    main()
