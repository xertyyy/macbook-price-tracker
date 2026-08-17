"""
Generischer Scraper: EIN Ablauf (SiteSpec + scrape_site) statt vier fast
identischer Funktionen. Neue Marktplaetze = ein neuer SITES-Eintrag.
"""
import re
import sys
import time
import random
from dataclasses import dataclass
from urllib.parse import quote_plus

import requests
from bs4 import BeautifulSoup

from tracker.config import HEADERS, REQUEST_TIMEOUT, SITE_DELAY_RANGE, is_broken


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
    "ebay": SiteSpec(
        key="ebay",
        label="eBay.de",
        build_url=lambda q: (
            "https://www.ebay.de/sch/i.html"
            f"?_nkw={quote_plus(q)}"
            "&LH_ItemCondition=3000"
            "&_sacat=0"
        ),
        card_sel=".s-item",
        title_sel=".s-item__title",
        price_sel=".s-item__price",
        link_sel="a.s-item__link",
        base_url="",
    ),
    "backmarket": SiteSpec(
        key="backmarket",
        label="Back Market",
        build_url=lambda q: f"https://www.backmarket.de/de-de/search?q={quote_plus(q)}",
        card_sel="[data-qa='productCard'], article",
        title_sel="[data-qa='productCardTitle'], h2, h3",
        price_sel="[data-qa='productCardPrice'], [class*='price']",
        link_sel="a[href]",
        base_url="https://www.backmarket.de",
    ),
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


def _parse_price(raw):
    if not raw:
        return None
    cleaned = re.sub(r"[^\d,.]", "", raw).replace(".", "").replace(",", ".")
    m = re.search(r"\d+(\.\d+)?", cleaned)
    try:
        return float(m.group()) if m else None
    except ValueError:
        return None


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
    if product.required_keywords and not all(k in lowered for k in product.required_keywords):
        return False
    if any(k in lowered for k in product.exclude_keywords):
        return False
    return True


def scrape_site(spec, query, product):
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
        if not accept(title, price, product):
            continue

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
    """Durchsucht alle in product.sources aktivierten Marktplaetze mit allen
    product.queries-Varianten und liefert deduplizierte Treffer zurueck."""
    offers = []
    active_sites = [SITES[key] for key in product.sources if key in SITES]
    tasks = [(site, query) for site in active_sites for query in product.queries]

    for index, (site, query) in enumerate(tasks):
        try:
            found = scrape_site(site, query, product)
            print(f"{site.label} ('{query}'): {len(found)} Treffer")
            offers.extend(found)
        except Exception as exc:
            print(f"{site.label} ('{query}') Fehler: {exc}", file=sys.stderr)
        if index < len(tasks) - 1:
            delay = random.uniform(*SITE_DELAY_RANGE)
            time.sleep(delay)

    deduped = _dedupe_offers(offers)
    print(f"{len(offers)} Rohtreffer, {len(deduped)} nach Entfernen von Duplikaten.")
    return deduped
