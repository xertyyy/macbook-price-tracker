"""
KI-Schicht (Google Gemini, kostenloser Free-Tier). Zwei Aufgaben:

1. build_product_config(): wandelt einen Produktnamen ("PS5 Slim") einmalig
   in eine Scraping-Konfiguration um (Suchbegriffe, Schluesselwoerter, Quellen).
2. apply_offer_ratings(): bewertet UND filtert die gefundenen Angebote eines
   Laufs. Der Marktpreis wird NICHT hartcodiert, sondern aus der tatsaechlichen
   Preisverteilung dieses Laufs geschaetzt (per KI + Statistik) — funktioniert
   dadurch fuer jedes beliebige Produkt ohne manuelle Konfiguration.
"""
import json
import statistics
import sys

import requests

from tracker.config import GEMINI_MODEL_CANDIDATES
from tracker.models import ALL_SOURCES

GEMINI_RATING_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "markt_referenz": {
            "type": "OBJECT",
            "properties": {
                "geschaetzter_marktpreis": {"type": "NUMBER"},
                "spanne_von": {"type": "NUMBER"},
                "spanne_bis": {"type": "NUMBER"},
                "begruendung": {"type": "STRING"},
            },
            "required": ["geschaetzter_marktpreis", "spanne_von", "spanne_bis", "begruendung"],
        },
        "ratings": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "index": {"type": "INTEGER"},
                    "passt_zum_produkt": {"type": "BOOLEAN"},
                    "begruendung": {"type": "STRING"},
                },
                "required": ["index", "passt_zum_produkt", "begruendung"],
            },
        },
    },
    "required": ["markt_referenz", "ratings"],
}

BUILD_CONFIG_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "queries": {"type": "ARRAY", "items": {"type": "STRING"}},
        "required_keywords": {"type": "ARRAY", "items": {"type": "STRING"}},
        "exclude_keywords": {"type": "ARRAY", "items": {"type": "STRING"}},
        "min_price": {"type": "NUMBER"},
        "sources": {
            "type": "ARRAY",
            "items": {"type": "STRING", "enum": ALL_SOURCES},
        },
    },
    "required": ["queries", "required_keywords", "exclude_keywords", "min_price", "sources"],
}


def _call_gemini(prompt, schema, api_key):
    """Ruft Gemini mit erzwungenem JSON-Schema auf und probiert dabei mehrere
    Modellnamen der Reihe nach durch (siehe GEMINI_MODEL_CANDIDATES)."""
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseSchema": schema,
        },
    }

    last_exc = None
    for model in GEMINI_MODEL_CANDIDATES:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        try:
            resp = requests.post(url, params={"key": api_key}, json=body, timeout=60)
            if resp.status_code == 404:
                last_exc = requests.HTTPError(f"Modell '{model}' nicht verfuegbar (404)")
                continue
            resp.raise_for_status()
            data = resp.json()
            text = data["candidates"][0]["content"]["parts"][0]["text"]
            return json.loads(text)
        except (requests.RequestException, KeyError, IndexError, ValueError) as exc:
            # KeyError/IndexError: z. B. leere/fehlende "candidates" (Gemini
            # hat sicherheitsgefiltert). ValueError deckt auch json.JSONDecodeError
            # ab (Modell liefert kein valides JSON). Ohne diese drei wuerde ein
            # einzelnes fehlerhaftes Modell den kompletten Aufruf abbrechen,
            # statt die naechsten Kandidaten in GEMINI_MODEL_CANDIDATES zu probieren.
            last_exc = exc
            continue

    raise last_exc or RuntimeError("Kein Gemini-Modell aus GEMINI_MODEL_CANDIDATES verfuegbar")


def compute_tier_from_percentile(price, stats):
    """Ordnet eine Qualitaetsstufe rein aus der Preis-Position innerhalb der
    tatsaechlich gefundenen Preise DIESES Laufs zu (Quartile) — bewusst NICHT
    von der KI-Marktpreis-Schaetzung abhaengig, weil deren absoluter Wert je
    nach Produktwissen der KI daneben liegen kann (z. B. zu hoch geschaetzt,
    wodurch sonst ploetzlich JEDES Angebot als 'Top-Deal' erscheint). Die
    Quartile der real gefundenen Angebote sind dagegen immer kalibriert."""
    if not stats:
        return "Okay"
    if price <= stats["p25"]:
        return "Top-Deal"
    if price <= stats["median"]:
        return "Gut"
    if price <= stats["p75"]:
        return "Okay"
    return "Vorsicht"


def compute_price_stats(prices):
    """Liefert Min/Quartile/Median/Max fuer die gefundenen Preise dieses Laufs
    (Ersatz fuer den frueher hartcodierten Marktpreis-Anchor)."""
    if not prices:
        return None
    sorted_prices = sorted(prices)
    if len(sorted_prices) == 1:
        p = sorted_prices[0]
        return {"min": p, "p25": p, "median": p, "p75": p, "max": p, "count": 1}
    quartiles = statistics.quantiles(sorted_prices, n=4)
    return {
        "min": sorted_prices[0],
        "p25": quartiles[0],
        "median": statistics.median(sorted_prices),
        "p75": quartiles[2],
        "max": sorted_prices[-1],
        "count": len(sorted_prices),
    }


def build_product_config(product_name, api_key):
    """Wandelt einen Produktnamen in eine Scraping-Konfiguration um. Faellt bei
    fehlendem Key oder KI-Fehlern auf eine simple Heuristik zurueck (der
    Tracker funktioniert dann trotzdem, nur weniger praezise)."""
    fallback = {
        "queries": [product_name],
        "required_keywords": [_fallback_keyword(product_name)],
        "exclude_keywords": [],
        "min_price": 0.0,
        "sources": list(ALL_SOURCES),
    }
    if not api_key:
        return fallback

    prompt = (
        f"Produkt: \"{product_name}\". Erstelle eine Scraping-Konfiguration fuer "
        "deutsche Gebrauchtmarkt-Plattformen (Kleinanzeigen.de, eBay.de, Back "
        "Market, refurbed):\n"
        "- queries: 3-5 unterschiedlich formulierte Suchbegriff-Varianten, wie "
        "Verkaeufer das Produkt typischerweise betiteln\n"
        "- required_keywords: 1-2 breite, IMMER im Titel vorkommende Anker-"
        "Woerter (klein geschrieben) — NICHT der komplette Produktname, da das "
        "sonst kaum ein Angebot matcht\n"
        "- exclude_keywords: typische Begriffe fuer Angebote, die NICHT das "
        "Produkt selbst sind (Zubehoer, Huelle, Ersatzteil, anderes Modell)\n"
        "- min_price: realistische Preis-Untergrenze in EUR, unter der ein "
        "Treffer sicher nicht das echte Produkt ist\n"
        "- sources: welche der 4 Plattformen fuer dieses Produkt sinnvoll sind"
    )
    try:
        result = _call_gemini(prompt, BUILD_CONFIG_SCHEMA, api_key)
        return {
            "queries": result.get("queries") or fallback["queries"],
            "required_keywords": [k.lower() for k in result.get("required_keywords", [])] or fallback["required_keywords"],
            "exclude_keywords": [k.lower() for k in result.get("exclude_keywords", [])],
            "min_price": float(result.get("min_price") or 0),
            "sources": [s for s in result.get("sources", []) if s in ALL_SOURCES] or fallback["sources"],
        }
    except Exception as exc:
        print(f"build_product_config KI-Fehler, nutze Fallback: {exc}", file=sys.stderr)
        return fallback


def _fallback_keyword(product_name):
    tokens = [t for t in product_name.lower().split() if len(t) > 2]
    return max(tokens, key=len) if tokens else product_name.lower()


def classify_price_fallback(price, stats):
    """Einfache Preis-Einstufung ohne KI, aus den Quartilen DIESES Laufs
    (Fallback, falls kein GEMINI_API_KEY gesetzt ist oder die KI-Analyse
    fehlschlaegt). Gibt None zurueck, wenn das Angebot zu teuer ist (oberstes
    Quartil wird hier komplett ausgefiltert statt als 'Vorsicht' gezeigt,
    da ohne KI-Relevanzpruefung vorsichtiger gefiltert werden sollte)."""
    if not stats:
        return None
    if price <= stats["p25"]:
        return "Schnaeppchen"
    if price <= stats["median"]:
        return "Guter Preis"
    return None


def _fallback_rate(offers, stats):
    kept = []
    for offer in offers:
        tier = classify_price_fallback(offer["price"], stats)
        if tier is None:
            continue
        offer["tier"] = tier
        offer["tier_note"] = ""
        kept.append(offer)
    market = {"geschaetzter_marktpreis": stats["median"]} if stats else None
    return kept, market


def _rate_with_ai(product_name, offers, stats, api_key):
    listing_lines = "\n".join(
        f"{i}. Titel: \"{o['title']}\" | Preis: {o['price']:.2f} EUR | Quelle: {o['source']}"
        for i, o in enumerate(offers)
    )
    stats_text = (
        f"Minimum {stats['min']:.2f} · 25%-Quartil {stats['p25']:.2f} · "
        f"Median {stats['median']:.2f} · 75%-Quartil {stats['p75']:.2f} · "
        f"Maximum {stats['max']:.2f} EUR ({stats['count']} Angebote)"
    ) if stats else "keine Preisdaten in diesem Lauf"

    prompt = (
        f"Produkt: \"{product_name}\" — gebrauchte/refurbished Angebote von "
        "deutschen Gebrauchtmarkt-Plattformen fuer einen persoenlichen "
        "Preis-Tracker.\n\n"
        f"Preisverteilung in DIESEM Suchlauf: {stats_text}\n\n"
        "Aufgabe 1: Schaetze einen realistischen Marktpreis in EUR fuer ein "
        "gebrauchtes/aufbereitetes Exemplar dieses Produkts in Deutschland. "
        "WICHTIG: gewichte die tatsaechliche Preisverteilung oben STARK hoeher "
        "als dein eigenes, moeglicherweise veraltetes Produktwissen — die "
        "Verteilung zeigt echte, aktuelle Angebote, dein Wissen kann falsch "
        "kalibriert sein (z. B. veralteter Neupreis). Nutze dein Produktwissen "
        "nur, um offensichtliche Ausreisser in der Verteilung zu erkennen.\n\n"
        "Aufgabe 2: Ordne JEDES der folgenden Angebote ein:\n"
        "- passt_zum_produkt=false, wenn der Titel offensichtlich NICHT das "
        "gesuchte Produkt ist (z. B. nur Zubehoer, Huelle, Ersatzteil, ein "
        "anderes Modell/andere Ausstattung, ein Konvolut)\n"
        "- begruendung: EIN kurzer deutscher Satz zum Zustand/zur Ausstattung "
        "laut Titel (z. B. \"Wirkt neuwertig, OVP erwaehnt\" oder \"Zustand "
        "unklar, wenig Angaben\"), max. 100 Zeichen. Die Preis-Einstufung "
        "macht der Tracker selbst anhand der Verteilung, dazu brauchst du "
        "nichts zu sagen.\n\n"
        f"{listing_lines}\n\n"
        "Gib fuer JEDES Angebot genau einen Eintrag in 'ratings' zurueck."
    )
    return _call_gemini(prompt, GEMINI_RATING_SCHEMA, api_key)


def apply_offer_ratings(offers, product_name, api_key):
    """Bewertet UND filtert Angebote. Gibt (angenommene_offers, markt_info)
    zurueck. 'markt_info' enthaelt mindestens 'geschaetzter_marktpreis'
    (oder ist None, wenn keine Referenz ermittelt werden konnte)."""
    if not offers:
        return [], None

    stats = compute_price_stats([o["price"] for o in offers])

    if not api_key:
        print("GEMINI_API_KEY nicht gesetzt — nutze Median-basierte Preis-Einstufung statt KI-Analyse.")
        return _fallback_rate(offers, stats)

    try:
        result = _rate_with_ai(product_name, offers, stats, api_key)
        market = result.get("markt_referenz") or None
        estimate = market.get("geschaetzter_marktpreis") if market else None
        ratings = result.get("ratings", [])
        rating_by_index = {r["index"]: r for r in ratings if isinstance(r, dict) and "index" in r}

        kept = []
        missing_count = 0
        rejected_count = 0
        too_expensive_count = 0
        for i, offer in enumerate(offers):
            rating = rating_by_index.get(i)
            if rating is None:
                # Gemini hat fuer diesen Index keinen Eintrag geliefert (bei
                # langen Listen kommt das vor) — das ist NICHT dasselbe wie
                # eine explizite Ablehnung, daher separat gezaehlt statt
                # stillschweigend wie ein passt_zum_produkt=false behandelt.
                missing_count += 1
                continue
            if not rating.get("passt_zum_produkt", True):
                rejected_count += 1
                continue
            # "estimate is not None" statt "estimate": eine Schaetzung von
            # exakt 0.0 ist ein gueltiger (wenn auch seltener) Wert und soll
            # den Preisdeckel weiterhin anwenden, nicht per Falsy-Check umgehen.
            if estimate is not None and offer["price"] > estimate * 1.05:
                too_expensive_count += 1
                continue
            offer["tier"] = compute_tier_from_percentile(offer["price"], stats)
            offer["tier_note"] = rating.get("begruendung", "")
            kept.append(offer)

        print(f"KI-Analyse: {len(kept)}/{len(offers)} Angebote relevant + im Preisrahmen "
              f"(Markt-Schaetzung: {estimate} EUR). Verworfen: {rejected_count} nicht "
              f"passend, {too_expensive_count} zu teuer, {missing_count} von der KI "
              f"nicht bewertet.")
        return kept, market
    except Exception as exc:
        print(f"KI-Analyse fehlgeschlagen, nutze Median-basierte Einstufung: {exc}", file=sys.stderr)
        return _fallback_rate(offers, stats)
