"""
Baut Discord-Embeds aus bewerteten Angeboten und sendet sie per Webhook.
Generalisiert (Produktname statt hartcodiertem "MacBook Pro 14 M2 Pro") und
zeigt die KI-Begruendung (tier_note) direkt unter jedem Angebot an.
"""
import sys
from datetime import datetime, timezone

import requests

from tracker.config import COLOR_GREEN, COLOR_ORANGE, DASHBOARD_URL, TIER_EMOJI, REQUEST_TIMEOUT

# Discord-Grenzen: max. 25 Felder pro Embed UND max. 6000 Zeichen insgesamt
# ueber ALLE Embeds einer Nachricht. Wir bleiben bei EINEM Embed pro Nachricht
# und halten uns bewusst unter beiden Grenzen (Sicherheitsmarge), damit lange
# Titel/Links nie zu einem 400-Fehler ("Bad Request") fuehren. Bei mehr
# Angeboten als in eine Nachricht passen, werden mehrere Nachrichten gesendet.
MAX_FIELDS_PER_EMBED = 20
MAX_EMBED_CHARS = 5000
MAX_MESSAGES = 10


def count_by_source(offers):
    """Zaehlt Angebote je Quelle, z.B. {'Kleinanzeigen.de': 24, 'eBay.de': 3}."""
    counts = {}
    for offer in offers:
        counts[offer["source"]] = counts.get(offer["source"], 0) + 1
    return counts


def _format_source_counts(counts):
    if not counts:
        return ""
    parts = [f"{source}: {count}" for source, count in sorted(counts.items(), key=lambda kv: -kv[1])]
    return " · ".join(parts)


def _offer_field(offer):
    tier = offer.get("tier", "Unbewertet")
    emoji = TIER_EMOJI.get(tier, "⚪")
    title_short = offer["title"] if len(offer["title"]) <= 70 else offer["title"][:69] + "…"
    value = f"[{title_short}]({offer['link']})"

    note = offer.get("tier_note")
    if note:
        note_short = note if len(note) <= 120 else note[:119] + "…"
        value += f"\n_{note_short}_"

    return {
        "name": f"{emoji}  {offer['price']:.2f} €  ·  {offer['source']}  ·  {tier}",
        "value": value,
        "inline": False,
    }


def build_offer_messages(product_name, offers, market_info=None, source_counts=None):
    """Baut eine Liste von Discord-Nachrichten-Payloads (je EIN Embed mit
    anklickbaren Angeboten + KI-Begruendung). Angebote werden nach Zeichen-/
    Feld-Budget auf mehrere Nachrichten aufgeteilt, damit Discords 6000-
    Zeichen-Limit pro Nachricht nie gerissen wird. Die erste Nachricht bekommt
    ein Vorschaubild und im Footer die Anzahl Angebote je Quelle plus (falls
    vorhanden) die KI-Marktschaetzung."""
    has_top_deal = any(offer.get("tier") in ("Top-Deal", "Schnaeppchen") for offer in offers)
    color = COLOR_GREEN if has_top_deal else COLOR_ORANGE
    now = datetime.now(timezone.utc).isoformat()

    field_chunks = []
    current_fields = []
    current_chars = 0

    for i, offer in enumerate(offers):
        field = _offer_field(offer)
        field_chars = len(field["name"]) + len(field["value"])
        if current_fields and (len(current_fields) >= MAX_FIELDS_PER_EMBED or current_chars + field_chars > MAX_EMBED_CHARS):
            field_chunks.append(current_fields)
            current_fields = []
            current_chars = 0
            # Erst NACH dem Schliessen eines Chunks pruefen, ob das Limit
            # erreicht ist -- sonst wird der zu diesem Zeitpunkt schon
            # begonnene (aber noch offene) Chunk am Schleifenende trotzdem
            # unconditional angehaengt und MAX_MESSAGES um eins ueberschritten.
            if len(field_chunks) >= MAX_MESSAGES:
                remaining = len(offers) - i
                print(f"HINWEIS: {remaining} weitere Angebote werden aus Nachrichten-Limit-Gruenden nicht gesendet.")
                break
        current_fields.append(field)
        current_chars += field_chars
    if current_fields and len(field_chunks) < MAX_MESSAGES:
        field_chunks.append(current_fields)

    total = len(field_chunks)
    payloads = []
    for idx, fields in enumerate(field_chunks):
        embed = {"color": color, "fields": fields}
        embed["title"] = (
            f"{product_name} — {len(offers)} Angebote gefunden"
            if total == 1
            else f"{product_name} — Teil {idx + 1}/{total} ({len(offers)} Angebote gesamt)"
        )
        if idx == 0:
            embed["timestamp"] = now
            embed["description"] = f"📊 [Alle Angebote im Dashboard ansehen]({DASHBOARD_URL})"
            best_image = next(
                (o["image"] for o in offers if o.get("image") and o["image"].startswith("http")),
                None,
            )
            if best_image:
                embed["image"] = {"url": best_image}
            estimate = (market_info or {}).get("geschaetzter_marktpreis")
            footer_parts = []
            if source_counts:
                footer_parts.append(_format_source_counts(source_counts))
            if estimate:
                footer_parts.append(f"KI-Marktschaetzung: ~{estimate:.0f} €")
            if footer_parts:
                embed["footer"] = {"text": " · ".join(footer_parts)}
        payloads.append({
            "content": "@everyone Top-Deal(s) gefunden!" if (has_top_deal and idx == 0) else "",
            "embeds": [embed],
        })

    return payloads, has_top_deal


def build_checkin_message(product_summaries):
    """Baut eine kompakte Tages-Uebersicht mit Dashboard-Link, unabhaengig
    davon ob gerade neue Angebote gefunden wurden. product_summaries:
    Liste von (produkt_name, guenstigstes_angebot_oder_None, source_counts)."""
    fields = []
    for name, best, source_counts in product_summaries[:25]:
        if best:
            value = f"Günstigstes aktuell: {float(best['price']):.2f} € ({best['source']})"
        else:
            value = "Noch keine Angebote gefunden."
        counts_text = _format_source_counts(source_counts)
        if counts_text:
            value += f"\n{counts_text}"
        fields.append({"name": name, "value": value, "inline": False})

    embed = {
        "title": "📊 Preis-Tracker — Tagesübersicht",
        "description": f"[Alle Angebote im Dashboard ansehen]({DASHBOARD_URL})",
        "color": COLOR_ORANGE,
        "fields": fields,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    return {"content": "", "embeds": [embed]}


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
