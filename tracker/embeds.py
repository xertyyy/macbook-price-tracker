"""
Baut Discord-Embeds aus bewerteten Angeboten und sendet sie per Webhook.
Generalisiert (Produktname statt hartcodiertem "MacBook Pro 14 M2 Pro") und
zeigt die KI-Begruendung (tier_note) direkt unter jedem Angebot an.
"""
import sys
from datetime import datetime, timezone

import requests

from tracker.config import COLOR_GREEN, COLOR_ORANGE, TIER_EMOJI, REQUEST_TIMEOUT

# Discord-Grenzen: max. 25 Felder pro Embed UND max. 6000 Zeichen insgesamt
# ueber ALLE Embeds einer Nachricht. Wir bleiben bei EINEM Embed pro Nachricht
# und halten uns bewusst unter beiden Grenzen (Sicherheitsmarge), damit lange
# Titel/Links nie zu einem 400-Fehler ("Bad Request") fuehren. Bei mehr
# Angeboten als in eine Nachricht passen, werden mehrere Nachrichten gesendet.
MAX_FIELDS_PER_EMBED = 20
MAX_EMBED_CHARS = 5000
MAX_MESSAGES = 10


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


def build_offer_messages(product_name, offers, market_info=None):
    """Baut eine Liste von Discord-Nachrichten-Payloads (je EIN Embed mit
    anklickbaren Angeboten + KI-Begruendung). Angebote werden nach Zeichen-/
    Feld-Budget auf mehrere Nachrichten aufgeteilt, damit Discords 6000-
    Zeichen-Limit pro Nachricht nie gerissen wird. Die erste Nachricht bekommt
    ein Vorschaubild und (falls vorhanden) die KI-Marktschaetzung im Footer."""
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
        field = _offer_field(offer)
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
            f"{product_name} — {len(offers)} Angebote gefunden"
            if total == 1
            else f"{product_name} — Teil {idx + 1}/{total} ({len(offers)} Angebote gesamt)"
        )
        if idx == 0:
            embed["timestamp"] = now
            best_image = next(
                (o["image"] for o in offers if o.get("image") and o["image"].startswith("http")),
                None,
            )
            if best_image:
                embed["image"] = {"url": best_image}
            estimate = (market_info or {}).get("geschaetzter_marktpreis")
            if estimate:
                embed["footer"] = {"text": f"KI-Marktschaetzung: ~{estimate:.0f} €"}
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
