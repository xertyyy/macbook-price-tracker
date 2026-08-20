"""
Vercel-Einstiegspunkt (Flask). Aktuell nur die eBay-"Marketplace Account
Deletion"-Verifizierung -- Voraussetzung, damit eBays Production-API-Keys
ueberhaupt freigeschaltet werden. Spaeter kommt hier auch der Discord-
Interactions-Endpoint (/api/interactions) fuer /track /deals etc. dazu.

Lokal testen: `python app.py` startet denselben Code auf http://localhost:8000
-- 1:1 derselbe Pfad wie auf Vercel, kein separater Dev-Server noetig.
"""
import hashlib
import os

from flask import Flask, jsonify, request

app = Flask(__name__)

# Muss EXAKT mit dem Wert im eBay Developer Portal (Alerts & Notifications ->
# Marketplace Account Deletion -> Verification Token) uebereinstimmen.
EBAY_VERIFICATION_TOKEN = os.getenv("EBAY_VERIFICATION_TOKEN", "")

# Muss EXAKT der URL entsprechen, die im eBay-Portal als Endpunkt eingetragen
# ist (inkl. https://, ohne Trailing Slash falls dort auch keiner steht).
EBAY_ENDPOINT_URL = os.getenv("EBAY_ENDPOINT_URL", "")


@app.get("/api/ebay-deletion")
def ebay_deletion_verify():
    """eBay ruft das beim Speichern der Endpunkt-Konfiguration mit
    ?challenge_code=... auf, um zu pruefen, dass wir wirklich die Inhaber
    dieses Endpunkts sind. Algorithmus laut eBay-Doku:
    SHA256(challengeCode + verificationToken + endpointUrl), hex-codiert."""
    challenge_code = request.args.get("challenge_code", "")
    combined = challenge_code + EBAY_VERIFICATION_TOKEN + EBAY_ENDPOINT_URL
    digest = hashlib.sha256(combined.encode("utf-8")).hexdigest()
    return jsonify({"challengeResponse": digest})


@app.post("/api/ebay-deletion")
def ebay_deletion_notify():
    """Tatsaechliche Loeschungs-Benachrichtigungen. Wir speichern keinerlei
    persoenliche eBay-Nutzerdaten (nur oeffentliche Angebotsdaten ueber die
    Browse-API, App-Only-OAuth ohne Nutzeranmeldung) -- es gibt hier also
    nichts zu loeschen. Einfach quittieren."""
    return jsonify({"status": "ok"}), 200


@app.get("/health")
def health():
    return jsonify(ok=True)


if __name__ == "__main__":
    app.run(port=8000, debug=True)
