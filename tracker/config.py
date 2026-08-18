"""
Generische Konfiguration: Umgebungsvariablen, HTTP-Header, Anti-Bot-Delays,
Qualitaetsstufen und Discord-Farben. Alles hier ist produkt-unabhaengig.
"""
import random

from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Discord Embed-Farben
# ---------------------------------------------------------------------------
COLOR_GREEN  = 0x00FF00
COLOR_ORANGE = 0xFFA500
COLOR_RED    = 0xFF0000

# Live-Dashboard (dashboard/index.html), gehostet ueber GitHub Pages. Wird
# in jede Discord-Nachricht als klickbarer Link eingebettet. Falls das Repo
# umbenannt/verschoben wird, hier anpassen.
DASHBOARD_URL = "https://xertyyy.github.io/macbook-price-tracker/dashboard/"

# ---------------------------------------------------------------------------
# Google-Gemini-Modelle fuer die KOSTENLOSE KI-Bewertung (Free-Tier ueber
# Google AI Studio, siehe README). Google stellt Modelle regelmaessig ab
# (z. B. wurde gemini-2.0-flash am 1.6.2026 abgeschaltet) — deshalb wird der
# Reihe nach durchprobiert. Erstes verfuegbares Modell gewinnt. Falls
# irgendwann ALLE hier 404 liefern: auf ai.google.dev/gemini-api/docs/models
# nachschauen, welche Modelle aktuell im Free-Tier verfuegbar sind, und diese
# Liste aktualisieren.
GEMINI_MODEL_CANDIDATES = [
    "gemini-2.5-flash-lite",
    "gemini-2.5-flash",
    "gemini-flash-latest",
]

# Reihenfolge/Sortierung und Emoji je Qualitaetsstufe. "Schnaeppchen" und
# "Guter Preis" sind die Ersatz-Stufen, falls kein GEMINI_API_KEY gesetzt ist
# bzw. die KI-Analyse fehlschlaegt (dann wird rein nach Preis bewertet).
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

# Maximale Anzahl Angebote, die pro Produkt und Lauf an Discord gesendet
# werden (die besten zuerst: hoechste Qualitaetsstufe, dann guenstigster
# Preis). Rest wird nur geloggt.
MAX_OFFERS_TO_SHOW = 25

# Woerter im Titel, bei denen ein Angebot als defekt/beschaedigt gilt und
# NICHT gemeldet wird — produktunabhaengig. Hier kannst du weitere Begriffe
# ergaenzen.
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
