"""
eBay ueber die OFFIZIELLE Browse-API statt HTML-Scraping.

Grund: eBay blockiert HTML-Scraping-Anfragen von GitHub-Actions-IPs mit
HTTP 403 (IP-Reputations-Sperre). Die Browse-API ist der offiziell
unterstuetzte, kostenlose Weg an dieselben Daten -- kein Umgehen von
irgendetwas, einfach der richtige Zugang statt des falschen.

Braucht einen kostenlosen eBay-Developer-Account (developer.ebay.com) und
die zwei Umgebungsvariablen EBAY_CLIENT_ID / EBAY_CLIENT_SECRET.
"""
import base64
import os
import sys
import time

import requests

EBAY_TOKEN_URL = "https://api.ebay.com/identity/v1/oauth2/token"
EBAY_SEARCH_URL = "https://api.ebay.com/buy/browse/v1/item_summary/search"

# Cache des Access Tokens fuer die Laufzeit des Prozesses (ein Tracker-Lauf
# braucht i.d.R. nur einen einzigen Token fuer alle Suchanfragen).
_token_cache = {"value": None, "expires_at": 0}


def _get_access_token():
    now = time.time()
    if _token_cache["value"] and now < _token_cache["expires_at"] - 60:
        return _token_cache["value"]

    client_id = os.getenv("EBAY_CLIENT_ID")
    client_secret = os.getenv("EBAY_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise RuntimeError("EBAY_CLIENT_ID/EBAY_CLIENT_SECRET nicht gesetzt")

    basic = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    headers = {
        "Authorization": f"Basic {basic}",
        "Content-Type": "application/x-www-form-urlencoded",
    }
    body = {
        "grant_type": "client_credentials",
        "scope": "https://api.ebay.com/oauth/api_scope",
    }
    resp = requests.post(EBAY_TOKEN_URL, headers=headers, data=body, timeout=15)
    resp.raise_for_status()
    data = resp.json()

    _token_cache["value"] = data["access_token"]
    _token_cache["expires_at"] = now + data.get("expires_in", 7200)
    return _token_cache["value"]


def search_ebay_offers(query):
    """Fragt die Browse-API ab und liefert RAW-Kandidaten (Titel/Preis/Link/
    Bild) OHNE Preis-/Relevanz-Filterung — die passiert zentral in
    tracker/scrapers.py:collect_offers_for_product(). Gibt bei fehlenden
    Zugangsdaten oder API-Fehlern eine leere Liste zurueck (Aufrufer faengt
    das bereits ab), damit ein eBay-Problem nicht den ganzen Lauf abbricht."""
    try:
        token = _get_access_token()
    except Exception as exc:
        print(f"[eBay API] Token-Fehler: {exc}", file=sys.stderr)
        return []

    headers = {
        "Authorization": f"Bearer {token}",
        "X-EBAY-C-MARKETPLACE-ID": "EBAY_DE",
    }
    params = {
        "q": query,
        # Nur gebrauchte/aufbereitete Artikel, keine Neuware.
        "filter": "conditions:{USED|CERTIFIED_REFURBISHED|SELLER_REFURBISHED}",
        "limit": "50",
    }

    try:
        resp = requests.get(EBAY_SEARCH_URL, headers=headers, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as exc:
        print(f"[eBay API] Fehler: {exc}", file=sys.stderr)
        return []

    results = []
    for item in data.get("itemSummaries", []):
        title = item.get("title")
        link = item.get("itemWebUrl")
        price_info = item.get("price") or {}
        # Trotz X-EBAY-C-MARKETPLACE-ID: EBAY_DE kann die Browse API vereinzelt
        # Cross-Border-/Global-Shipping-Angebote mit abweichender Waehrung
        # liefern. Ohne diese Pruefung wuerde z. B. ein USD-Preis ungeprueft
        # als EUR behandelt.
        currency = price_info.get("currency")
        if currency and currency != "EUR":
            continue
        try:
            price = float(price_info.get("value"))
        except (TypeError, ValueError):
            continue
        if not title or not link:
            continue

        image = (item.get("image") or {}).get("imageUrl")
        results.append({
            "source": "eBay.de",
            "title": title,
            "price": price,
            "link": link,
            "image": image,
        })
    return results
