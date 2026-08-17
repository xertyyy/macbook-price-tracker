# MacBook Pro 14 M2 Pro — Preis-Tracker

Trackt automatisch den Preis des MacBook Pro 14" M2 Pro (16GB RAM, 512GB SSD) auf
Kleinanzeigen.de, eBay.de, Back Market und refurbed. Alle 30 Minuten wird eine
einzige Discord-Nachricht mit einer Tabelle aller guten Angebote gesendet
(zu teure Angebote und defekte Geraete werden automatisch aussortiert).

Optional bewertet Claude (Anthropic API) jedes Angebot anhand des Titels mit
einer Qualitaetsstufe (Top-Deal / Gut / Okay / Vorsicht). Ohne API-Key stuft
der Tracker automatisch nur nach Preis ein — der Tracker funktioniert in
beiden Faellen.

## Setup — Schritt fuer Schritt

### 1. Discord-Webhook erstellen
1. Discord oeffnen, in den gewuenschten Server/Kanal gehen.
2. Kanal-Einstellungen -> **Integrationen** -> **Webhooks** -> **Neuer Webhook**.
3. **Webhook-URL kopieren**.

### 2. (Optional) Anthropic API-Key fuer die KI-Bewertung erstellen
Ohne diesen Schritt funktioniert der Tracker trotzdem — er stuft Angebote dann
nur nach Preis ein (Schnaeppchen / Guter Preis) statt per KI-Analyse.

1. Gehe zu [console.anthropic.com](https://console.anthropic.com) und melde dich an
   bzw. erstelle ein Konto.
2. Hinterlege etwas Guthaben unter **Billing** (dieser Tracker verbraucht durch die
   geringe Textmenge nur Cent-Betraege pro Monat, auch bei einem Lauf alle 30 Min).
3. Gehe zu **API Keys** -> **Create Key**, gib ihm einen Namen (z. B. `price-tracker`).
4. Kopiere den angezeigten Key (beginnt mit `sk-ant-...`) — er wird nur einmal angezeigt.

### 3. Projekt auf GitHub hochladen
```bash
git init
git add .
git commit -m "Initial commit: MacBook Preis-Tracker"
git branch -M main
git remote add origin https://github.com/DEIN-USERNAME/DEIN-REPO.git
git push -u origin main
```

### 4. Secrets in GitHub hinterlegen
1. Im GitHub-Repository: **Settings** -> **Secrets and variables** -> **Actions**.
2. **New repository secret** klicken.
3. Name: `DISCORD_WEBHOOK_URL`, Wert: die in Schritt 1 kopierte Webhook-URL. **Add secret**.
4. Optional fuer die KI-Bewertung: nochmal **New repository secret**, Name:
   `ANTHROPIC_API_KEY`, Wert: der in Schritt 2 kopierte Key. **Add secret**.

### 5. Tracker aktivieren
- Der Workflow unter `.github/workflows/price_tracker.yml` startet automatisch alle
  30 Minuten (GitHub Actions Cron-Schedule).
- Manuell testen: Im Repository auf **Actions** -> **MacBook Price Tracker** ->
  **Run workflow** klicken.

### 6. Preisgrenzen anpassen (optional)
Oeffne [`price_tracker.py`](price_tracker.py) und passe am Anfang der Datei die
Konstanten `PRICE_THRESHOLD_BARGAIN` und `PRICE_THRESHOLD_GOOD` an — keine
Programmierkenntnisse notwendig, einfach die Zahl aendern. Angebote oberhalb
von `PRICE_THRESHOLD_GOOD` werden generell nicht an Discord gemeldet.

## Lokal testen
```bash
pip install -r requirements.txt
cp .env.example .env
# .env oeffnen und DISCORD_WEBHOOK_URL (und optional ANTHROPIC_API_KEY) eintragen
python price_tracker.py
```

## Wie die Discord-Nachricht aussieht
Ein Lauf erzeugt genau eine Nachricht mit einer Tabelle (Stufe, Preis, Quelle,
gekuerzter Titel) und darunter klickbaren Links zu jedem Angebot. Ist ein
"Top-Deal"/"Schnaeppchen" dabei, wird zusaetzlich `@everyone` gepingt und die
Nachricht gruen eingefaerbt, sonst orange.

## Bekannte Einschraenkung: eBay & Back Market
GitHub-Actions-Runner laufen aus bekannten Cloud-Rechenzentrums-IP-Bereichen.
Enterprise-Bot-Schutz (wie ihn eBay und Back Market einsetzen) blockiert solche
IPs teilweise pauschal mit HTTP 403 — das laesst sich vom Skript aus nicht
loesen. Kleinanzeigen.de und refurbed funktionieren zuverlaessig. Falls du auch
eBay/Back Market brauchst, muesste der Tracker auf einem Rechner mit
"normaler" (z. B. privater) IP-Adresse laufen statt auf GitHub Actions.

## Hinweis zu den Scrapern
Die Suchergebnis-Seiten der vier Plattformen koennen sich jederzeit aendern
(HTML-Struktur, Klassennamen). Falls ein Scraper irgendwann keine Treffer mehr
liefert, muessen die CSS-Selektoren in der jeweiligen `scrape_*`-Funktion in
`price_tracker.py` an die aktuelle Seitenstruktur angepasst werden. Ein Ausfall
einzelner Scraper bricht den Tracker nicht ab — die anderen Quellen werden
trotzdem ausgewertet. Verschiedene Suchbegriff-Varianten (`SEARCH_QUERIES`)
werden je Quelle automatisch durchprobiert, um moeglichst kein Angebot zu
uebersehen.
