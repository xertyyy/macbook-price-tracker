# MacBook Pro 14 M2 Pro — Preis-Tracker

Trackt automatisch den Preis des MacBook Pro 14" M2 Pro (16GB RAM, 512GB SSD) auf
Back Market, refurbed und Swappie und sendet alle 30 Minuten eine Discord-Nachricht
mit dem guenstigsten gefundenen Angebot.

## Setup — Schritt fuer Schritt

### 1. Discord-Webhook erstellen
1. Discord oeffnen, in den gewuenschten Server/Kanal gehen.
2. Kanal-Einstellungen -> **Integrationen** -> **Webhooks** -> **Neuer Webhook**.
3. **Webhook-URL kopieren**.

### 2. Projekt auf GitHub hochladen
```bash
git init
git add .
git commit -m "Initial commit: MacBook Preis-Tracker"
git branch -M main
git remote add origin https://github.com/DEIN-USERNAME/DEIN-REPO.git
git push -u origin main
```

### 3. Discord-Webhook als GitHub Secret hinterlegen
1. Im GitHub-Repository: **Settings** -> **Secrets and variables** -> **Actions**.
2. **New repository secret** klicken.
3. Name: `DISCORD_WEBHOOK_URL`
4. Wert: die in Schritt 1 kopierte Webhook-URL einfuegen.
5. **Add secret** klicken.

### 4. Tracker aktivieren
- Der Workflow unter `.github/workflows/price_tracker.yml` startet automatisch alle
  30 Minuten (GitHub Actions Cron-Schedule).
- Manuell testen: Im Repository auf **Actions** -> **MacBook Price Tracker** ->
  **Run workflow** klicken.

### 5. Preisgrenzen anpassen (optional)
Oeffne [`price_tracker.py`](price_tracker.py) und passe am Anfang der Datei die
Konstanten `PRICE_THRESHOLD_BARGAIN` und `PRICE_THRESHOLD_GOOD` an — keine
Programmierkenntnisse notwendig, einfach die Zahl aendern.

## Lokal testen
```bash
pip install -r requirements.txt
cp .env.example .env
# .env oeffnen und DISCORD_WEBHOOK_URL eintragen
python price_tracker.py
```

## Hinweis zu den Scrapern
Die Suchergebnis-Seiten von Back Market, refurbed und Swappie koennen sich jederzeit
aendern (HTML-Struktur, Klassenamen). Falls ein Scraper irgendwann keine Treffer mehr
liefert, muessen die CSS-Selektoren in der jeweiligen `scrape_*`-Funktion in
`price_tracker.py` an die aktuelle Seitenstruktur angepasst werden. Ein Ausfall
einzelner Scraper bricht den Tracker nicht ab — die anderen Quellen werden trotzdem
ausgewertet.
