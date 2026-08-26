"""
Sammelt Rohangebote aus mehreren Quellen: HTML-Scraping (SiteSpec +
scrape_site) fuer Kleinanzeigen.de/refurbed, offizielle API fuer eBay.de
(siehe tracker/ebay_api.py). Jede Quelle liefert nur RAW-Kandidaten
(Titel/Preis/Link/Bild) zurueck -- die eigentliche Preis-/Relevanz-Filterung
(accept()) passiert zentral in collect_offers_for_product(), damit sie nicht
pro Quelle dupliziert werden muss.
"""
import re
import sys
import time
import random
from dataclasses import dataclass
from urllib.parse import quote_plus

import requests
from bs4 import BeautifulSoup

from tracker.config import HEADERS, REQUEST_TIMEOUT, SITE_DELAY_RANGE, contains_keyword, is_broken
from tracker.ebay_api import search_ebay_offers


def _kleinanzeigen_slug(query):
    """Wandelt einen Suchbegriff in das Kleinanzeigen-URL-Format (a-b-c) um."""
    return re.sub(r"[^a-z0-9]+", "-", query.lower()).strip("-")


@dataclass(frozen=True)
class SiteSpec:
    key: str
    label: str
    build_url: object          # Callable[[str], str]
    card_sel: str
    title_sel: str
    price_sel: str
    link_sel: str              # None = das Karten-Element selbst ist der <a>-Link
    base_url: str


SITES = {
    "kleinanzeigen": SiteSpec(
        key="kleinanzeigen",
        label="Kleinanzeigen.de",
        build_url=lambda q: f"https://www.kleinanzeigen.de/s-{_kleinanzeigen_slug(q)}/k0",
        card_sel="article.aditem",
        title_sel=".ellipsis, h2",
        price_sel=".aditem-main--middle--price-shipping--price",
        link_sel="a[href]",
        base_url="https://www.kleinanzeigen.de",
    ),
    # eBay.de laeuft NICHT mehr ueber HTML-Scraping, sondern ueber die
    # offizielle Browse-API (tracker/ebay_api.py) -- siehe SOURCES unten.
    # Back Market bewusst NICHT enthalten: blockiert Anfragen von GitHub-
    # Actions-IPs kategorisch mit 403 (IP-Reputations-Sperre, keine offizielle
    # API vorhanden).
    "refurbed": SiteSpec(
        key="refurbed",
        label="refurbed",
        build_url=lambda q: f"https://www.refurbed.de/search?q={quote_plus(q)}",
        card_sel="a[href*='/p/']",
        title_sel="[class*='title'], h2, h3",
        price_sel="[class*='price']",
        link_sel=None,
        base_url="https://www.refurbed.de",
    ),
}


@dataclass(frozen=True)
class SourceHandler:
    key: str
    label: str
    fetch: object  # Callable[[str, Product], list[dict]] -> RAW, ungefilterte Kandidaten


def _make_html_handler(spec):
    return SourceHandler(key=spec.key, label=spec.label, fetch=lambda query, product: scrape_site(spec, query, product))


SOURCES = {
    "kleinanzeigen": _make_html_handler(SITES["kleinanzeigen"]),
    "refurbed": _make_html_handler(SITES["refurbed"]),
    "ebay": SourceHandler(key="ebay", label="eBay.de", fetch=lambda query, product: search_ebay_offers(query)),
}


def _parse_price(raw):
    """Findet den (kleinsten) vollstaendigen Preis-Betrag im Text. Sucht
    gezielt nach Ziffernfolgen mit Tausender-/Dezimaltrennern statt einfach
    ALLE Ziffern im Text zusammenzukleben — sonst wuerden zwei nebeneinander
    stehende Preise (z. B. Streichpreis+Aktionspreis: "1.099,00 €899,00 €")
    zu einer einzigen falschen Zahl verschmelzen. Bei mehreren gefundenen
    Preisen (Streichpreis-Fall) wird der kleinere genommen — das ist bei
    Rabatt-Anzeigen praktisch immer der tatsaechliche Angebotspreis."""
    if not raw:
        return None
    tokens = re.findall(r"\d[\d.,]*\d|\d", raw)
    prices = []
    for token in tokens:
        cleaned = token.replace(".", "").replace(",", ".")
        try:
            prices.append(float(cleaned))
        except ValueError:
            continue
    return min(prices) if prices else None


def accept(title, price, product):
    """Generischer Angebots-Filter: Preisgrenzen, Defekt-Woerter und die
    (breiten) Produkt-Schluesselwoerter. Feinere Relevanzpruefung ('ist das
    wirklich das gesuchte Produkt?') passiert erst in tracker/ai.py, weil
    reine Substring-Suche das bei generischen Produkten nicht leisten kann."""
    if price is None or price < product.min_price:
        return False
    if product.max_price and price > product.max_price:
        return False
    if is_broken(title):
        return False
    lowered = title.lower()
    if product.required_keywords and not all(contains_keyword(lowered, k) for k in product.required_keywords):
        return False
    if any(contains_keyword(lowered, k) for k in product.exclude_keywords):
        return False
    return True


def scrape_site(spec, query, product):
    """Laedt die Suchergebnis-Seite und liefert RAW-Kandidaten (Titel/Preis/
    Link/Bild) OHNE Preis-/Relevanz-Filterung — die passiert zentral in
    collect_offers_for_product()."""
    results = []
    url = spec.build_url(query)
    try:
        resp = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
    except requests.RequestException as exc:
        print(f"[{spec.label}] Fehler: {exc}", file=sys.stderr)
        return results

    soup = BeautifulSoup(resp.text, "lxml")
    for card in soup.select(spec.card_sel):
        title_el = card.select_one(spec.title_sel)
        price_el = card.select_one(spec.price_sel)
        link_el = card if spec.link_sel is None else card.select_one(spec.link_sel)
        if not (title_el and price_el and link_el):
            continue

        title = title_el.get_text(strip=True)
        price = _parse_price(price_el.get_text(strip=True))
        href = link_el.get("href", "")

        link = href if href.startswith("http") else f"{spec.base_url}{href}"
        img = card.select_one("img")
        results.append({
            "source": spec.label,
            "title": title,
            "price": price,
            "link": link,
            "image": img.get("src") if img else None,
        })
    return results


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


def collect_offers_for_product(product):
    """Durchsucht alle in product.sources aktivierten Quellen mit allen
    product.queries-Varianten, filtert zentral per accept() und liefert
    deduplizierte Treffer zurueck."""
    offers = []
    active_sources = [SOURCES[key] for key in product.sources if key in SOURCES]
    tasks = [(source, query) for source in active_sources for query in product.queries]

    for index, (source, query) in enumerate(tasks):
        try:
            raw = source.fetch(query, product)
            found = [o for o in raw if accept(o["title"], o["price"], product)]
            print(f"{source.label} ('{query}'): {len(found)}/{len(raw)} Treffer nach Filter")
            offers.extend(found)
        except Exception as exc:
            print(f"{source.label} ('{query}') Fehler: {exc}", file=sys.stderr)
        if index < len(tasks) - 1:
            delay = random.uniform(*SITE_DELAY_RANGE)
            time.sleep(delay)

    deduped = _dedupe_offers(offers)
    print(f"{len(offers)} Rohtreffer, {len(deduped)} nach Entfernen von Duplikaten.")
    return deduped
