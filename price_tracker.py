"""
Preis-Tracker fuer MacBook Pro 14 M2 Pro (16GB RAM, 512GB SSD)
Quellen: Kleinanzeigen.de und eBay.de
"""
import os
import random
import re
import sys
import time
from datetime import datetime, timezone
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# KONFIGURATION — hier kannst du Werte anpassen
# ---------------------------------------------------------------------------
PRICE_THRESHOLD_BARGAIN = 1100.0   # unter diesem Preis: GRUEN + @everyone-Ping
PRICE_THRESHOLD_GOOD    = 1150.0   # bis hier: GELB — darueber: ROT

COLOR_GREEN  = 0x00FF00
COLOR_YELLOW = 0xFFFF00
COLOR_RED    = 0xFF0000

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


# Pause zwischen einzelnen Discord-Nachrichten in Sekunden, um das Rate-Limit
# des Webhooks (max. ca. 30 Nachrichten/Minute) nicht zu ueberschreiten.
DISCORD_SEND_DELAY = 1.5

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

# ---------------------------------------------------------------------------
# SCRAPER: Kleinanzeigen.de
# ---------------------------------------------------------------------------
def scrape_kleinanzeigen():
    results = []
    url = "https://www.kleinanzeigen.de/s-macbook-pro-14-m2-pro/k0"
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
def scrape_ebay():
    results = []
    url = (
        "https://www.ebay.de/sch/i.html"
        "?_nkw=MacBook+Pro+14+M2+Pro+16GB+512GB"
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

def collect_all_offers():
    offers = []
    scrapers = [scrape_kleinanzeigen, scrape_ebay]
    for index, scraper in enumerate(scrapers):
        try:
            found = scraper()
            print(f"{scraper.__name__}: {len(found)} Treffer")
            offers.extend(found)
        except Exception as exc:
            print(f"{scraper.__name__} Fehler: {exc}", file=sys.stderr)
        if index < len(scrapers) - 1:
            delay = random.uniform(*SITE_DELAY_RANGE)
            time.sleep(delay)
    return offers

# ---------------------------------------------------------------------------
# Discord Webhook
# ---------------------------------------------------------------------------
def send_discord_notification(offer, webhook_url):
    price = offer["price"]
    if price < PRICE_THRESHOLD_BARGAIN:
        color, ping = COLOR_GREEN, True
    elif price <= PRICE_THRESHOLD_GOOD:
        color, ping = COLOR_YELLOW, False
    else:
        color, ping = COLOR_RED, False

    embed = {
        "title": offer["title"],
        "url":   offer["link"],
        "description": f"**Preis:** {price:.2f} €\n**Quelle:** {offer['source']}",
        "color": color,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "fields": [{"name": "Direktlink", "value": f"[Zum Angebot]({offer['link']})", "inline": False}],
    }
    if offer.get("image"):
        embed["thumbnail"] = {"url": offer["image"]}

    payload = {
        "content": "@everyone Schnaeppchen gefunden!" if ping else "",
        "embeds": [embed],
    }
    try:
        resp = requests.post(webhook_url, json=payload, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        print("Discord-Nachricht gesendet.")
    except requests.RequestException as exc:
        print(f"Discord-Webhook Fehler: {exc}", file=sys.stderr)

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    webhook_url = os.getenv("DISCORD_WEBHOOK_URL")
    if not webhook_url:
        print("FEHLER: DISCORD_WEBHOOK_URL nicht gesetzt.", file=sys.stderr)
        sys.exit(1)

    startup_delay = random.uniform(*STARTUP_JITTER_RANGE)
    print(f"Warte {startup_delay:.1f}s (Start-Jitter) vor der ersten Anfrage...")
    time.sleep(startup_delay)

    offers = collect_all_offers()

    if not offers:
        print("Keine (funktionsfaehigen) Angebote gefunden.")
        return

    # Guenstigstes Angebot zuerst, damit es in Discord oben in der History steht
    offers_sorted = sorted(offers, key=lambda o: o["price"])

    print(f"{len(offers_sorted)} funktionsfaehige Angebote gefunden — sende alle an Discord.")
    for index, offer in enumerate(offers_sorted):
        print(f" - {offer['title']} — {offer['price']:.2f} € ({offer['source']})")
        send_discord_notification(offer, webhook_url)
        if index < len(offers_sorted) - 1:
            time.sleep(DISCORD_SEND_DELAY)

if __name__ == "__main__":
    main()
