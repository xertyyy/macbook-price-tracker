"""
Preis-Tracker fuer MacBook Pro 14 M2 Pro (16GB RAM, 512GB SSD)
auf seriosen deutschen Gebrauchtmarkt-Plattformen.

Sendet alle 30 Minuten (per GitHub Actions Cron) eine Discord-Nachricht
mit dem guenstigsten gefundenen Angebot.
"""

import os
import re
import sys
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# KONFIGURATION — hier kannst du ohne Programmierkenntnisse Werte anpassen
# ---------------------------------------------------------------------------

# Preisgrenzen in Euro
PRICE_THRESHOLD_BARGAIN = 1100.0   # unter diesem Preis: GRUEN + @everyone-Ping
PRICE_THRESHOLD_GOOD = 1150.0      # zwischen BARGAIN und hier: GELB (guter Deal)
                                    # darueber: ROT (zu teuer)

# Suchbegriff / Modellbeschreibung, wird fuer die Suche auf den Plattformen genutzt
SEARCH_QUERY = "MacBook Pro 14 M2 Pro 16GB 512GB"

# Discord Embed-Farben (Dezimalwerte, von Discord API erwartet)
COLOR_GREEN = 0x00FF00
COLOR_YELLOW = 0xFFFF00
COLOR_RED = 0xFF0000

# Realistischer Browser-User-Agent, um Blockaden durch einfache Bot-Filter zu vermeiden
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7",
}

REQUEST_TIMEOUT = 15  # Sekunden

# ---------------------------------------------------------------------------
# SCRAPER: Back Market
# ---------------------------------------------------------------------------

def scrape_back_market():
    """Sucht das MacBook Pro 14 M2 Pro auf Back Market (backmarket.de)."""
    results = []
    url = "https://www.backmarket.de/de-de/search?q=" + requests.utils.quote(SEARCH_QUERY)
    try:
        resp = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
    except requests.RequestException as exc:
        print(f"[Back Market] Anfrage fehlgeschlagen: {exc}", file=sys.stderr)
        return results

    soup = BeautifulSoup(resp.text, "lxml")
    # Back Market rendert Suchergebnisse in Produktkarten mit data-qa Attributen.
    cards = soup.select("[data-qa='productCard'], article")

    for card in cards:
        title_el = card.select_one("[data-qa='productCardTitle'], h2, h3")
        price_el = card.select_one("[data-qa='productCardPrice'], [class*='price']")
        link_el = card.select_one("a[href]")

        if not (title_el and price_el and link_el):
            continue

        title = title_el.get_text(strip=True)
        price = _parse_price(price_el.get_text(strip=True))
        href = link_el.get("href", "")

        if price is None or "macbook" not in title.lower():
            continue

        link = href if href.startswith("http") else f"https://www.backmarket.de{href}"
        image_el = card.select_one("img")
        image = image_el.get("src") if image_el else None

        results.append({
            "source": "Back Market",
            "title": title,
            "price": price,
            "link": link,
            "image": image,
        })

    return results


# ---------------------------------------------------------------------------
# SCRAPER: refurbed
# ---------------------------------------------------------------------------

def scrape_refurbed():
    """Sucht das MacBook Pro 14 M2 Pro auf refurbed (refurbed.de)."""
    results = []
    url = "https://www.refurbed.de/search?q=" + requests.utils.quote(SEARCH_QUERY)
    try:
        resp = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
    except requests.RequestException as exc:
        print(f"[refurbed] Anfrage fehlgeschlagen: {exc}", file=sys.stderr)
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
        href = card.get("href", "")

        if price is None or "macbook" not in title.lower():
            continue

        link = href if href.startswith("http") else f"https://www.refurbed.de{href}"
        image_el = card.select_one("img")
        image = image_el.get("src") if image_el else None

        results.append({
            "source": "refurbed",
            "title": title,
            "price": price,
            "link": link,
            "image": image,
        })

    return results


# ---------------------------------------------------------------------------
# SCRAPER: Swappie
# ---------------------------------------------------------------------------

def scrape_swappie():
    """
    Sucht das MacBook Pro 14 M2 Pro auf Swappie.

    Hinweis: Swappie fuehrt aktuell primaer iPhones im Sortiment.
    Sollte das Modell im Katalog auftauchen, greift dieser Scraper;
    andernfalls liefert er eine leere Liste (kein Fehler).
    """
    results = []
    url = "https://swappie.com/de/kaufen/macbook/"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
    except requests.RequestException as exc:
        print(f"[Swappie] Anfrage fehlgeschlagen: {exc}", file=sys.stderr)
        return results

    soup = BeautifulSoup(resp.text, "lxml")
    cards = soup.select("a[href*='/kaufen/']")

    for card in cards:
        title_el = card.select_one("[class*='title'], h2, h3")
        price_el = card.select_one("[class*='price']")

        if not (title_el and price_el):
            continue

        title = title_el.get_text(strip=True)
        price = _parse_price(price_el.get_text(strip=True))
        href = card.get("href", "")

        if price is None or "macbook" not in title.lower():
            continue

        link = href if href.startswith("http") else f"https://swappie.com{href}"
        image_el = card.select_one("img")
        image = image_el.get("src") if image_el else None

        results.append({
            "source": "Swappie",
            "title": title,
            "price": price,
            "link": link,
            "image": image,
        })

    return results


# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------

def _parse_price(raw_text):
    """Extrahiert einen float-Preis aus einem Text wie '1.199,00 €'."""
    if not raw_text:
        return None
    cleaned = re.sub(r"[^\d,.\s]", "", raw_text).strip()
    cleaned = cleaned.replace(".", "").replace(",", ".")
    match = re.search(r"\d+(\.\d+)?", cleaned)
    if not match:
        return None
    try:
        return float(match.group())
    except ValueError:
        return None


def collect_all_offers():
    """Ruft alle Scraper auf und sammelt die Ergebnisse in einer Liste."""
    scrapers = [scrape_back_market, scrape_refurbed, scrape_swappie]
    offers = []

    for scraper in scrapers:
        try:
            found = scraper()
            print(f"{scraper.__name__}: {len(found)} Treffer")
            offers.extend(found)
        except Exception as exc:  # Scraper-Ausfaelle sollen den Tracker nicht abbrechen
            print(f"{scraper.__name__} ist fehlgeschlagen: {exc}", file=sys.stderr)

    return offers


def pick_cheapest(offers):
    """Gibt das guenstigste Angebot aus der Liste zurueck, oder None."""
    if not offers:
        return None
    return min(offers, key=lambda offer: offer["price"])


# ---------------------------------------------------------------------------
# Discord Webhook
# ---------------------------------------------------------------------------

def determine_color_and_ping(price):
    """Bestimmt Embed-Farbe und ob @everyone gepingt werden soll."""
    if price < PRICE_THRESHOLD_BARGAIN:
        return COLOR_GREEN, True
    if price <= PRICE_THRESHOLD_GOOD:
        return COLOR_YELLOW, False
    return COLOR_RED, False


def send_discord_notification(offer, webhook_url):
    """Sendet ein Rich-Embed mit dem guenstigsten Angebot an Discord."""
    color, ping_everyone = determine_color_and_ping(offer["price"])

    embed = {
        "title": offer["title"],
        "url": offer["link"],
        "description": f"**Preis:** {offer['price']:.2f} €\n**Quelle:** {offer['source']}",
        "color": color,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "fields": [
            {"name": "Direktlink", "value": f"[Zum Angebot]({offer['link']})", "inline": False},
        ],
    }

    if offer.get("image"):
        embed["thumbnail"] = {"url": offer["image"]}

    payload = {
        "content": "@everyone Schnaeppchen gefunden!" if ping_everyone else "",
        "embeds": [embed],
    }

    try:
        resp = requests.post(webhook_url, json=payload, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        print("Discord-Nachricht erfolgreich gesendet.")
    except requests.RequestException as exc:
        print(f"Discord-Webhook fehlgeschlagen: {exc}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    webhook_url = os.getenv("DISCORD_WEBHOOK_URL")
    if not webhook_url:
        print("FEHLER: Umgebungsvariable DISCORD_WEBHOOK_URL ist nicht gesetzt.", file=sys.stderr)
        sys.exit(1)

    offers = collect_all_offers()
    cheapest = pick_cheapest(offers)

    if cheapest is None:
        print("Keine Angebote gefunden — es wird keine Nachricht gesendet.")
        return

    print(f"Guenstigstes Angebot: {cheapest['title']} — {cheapest['price']:.2f} € ({cheapest['source']})")
    send_discord_notification(cheapest, webhook_url)


if __name__ == "__main__":
    main()
