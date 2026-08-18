# MacBook Pro 14 M2 Pro — Preis-Tracker

Trackt automatisch Angebote fuer das MacBook Pro 14" M2 Pro (16GB RAM, 512GB SSD)
auf Kleinanzeigen.de, eBay.de (offizielle API) und refurbed. Ergebnisse landen in
einer geteilten Supabase-Datenbank und werden auf zwei Wegen sichtbar:

- **Discord**: eine Nachricht bei neu gefundenen Angeboten, plus einmal taeglich
  eine kompakte Uebersicht (Check-in) — beides mit Link zum Dashboard.
- **Live-Dashboard** ([dashboard/index.html](dashboard/index.html)): eine einzelne
  HTML-Seite, die direkt aus dem Browser gegen Supabase abfragt und alle
  aktuellen Angebote als saubere, farblich sortierte Karten zeigt.

Google Gemini (kostenloser Free-Tier) bewertet jedes Angebot: schaetzt aus der
tatsaechlichen Preisverteilung des aktuellen Laufs einen Marktpreis, prueft ob
der Titel wirklich zum gesuchten Produkt passt, und liefert eine kurze
Begruendung zu Zustand/Ausstattung. Ohne Gemini-Key faellt der Tracker auf eine
einfache, median-basierte Preis-Einstufung zurueck — er funktioniert in beiden
Faellen, nur weniger praezise ohne KI.

## Setup — Schritt fuer Schritt

### 1. Discord-Webhook erstellen
1. Discord oeffnen, in den gewuenschten Server/Kanal gehen.
2. Kanal-Einstellungen -> **Integrationen** -> **Webhooks** -> **Neuer Webhook**.
3. **Webhook-URL kopieren**.

### 2. (Optional) Kostenlosen Google-Gemini API-Key erstellen
Ohne diesen Schritt funktioniert der Tracker trotzdem — er stuft Angebote dann
nur nach dem Median dieses Laufs ein statt per KI-Analyse. Der Gemini-Key ist
dauerhaft **kostenlos** (Free-Tier, kein Kreditkarten-Zwang).

1. Gehe zu [aistudio.google.com/app/apikey](https://aistudio.google.com/app/apikey)
   und melde dich mit einem Google-Konto an.
2. Klicke auf **Create API key** (ggf. ein neues Projekt bestaetigen).
3. Kopiere den angezeigten Key.

Hinweis: Google kann die Free-Tier-Bedingungen (Rate-Limits, Modellnamen)
jederzeit aendern — sollte keines der Modelle in `GEMINI_MODEL_CANDIDATES`
(`tracker/config.py`) mehr funktionieren, auf ai.google.dev nach aktuellen
kostenlosen Flash-Modellen schauen und die Liste ergaenzen.

### 3. (Optional) Kostenlosen eBay-Developer-Account fuer die Browse-API erstellen
Ohne diesen Schritt sucht der Tracker nur auf Kleinanzeigen.de und refurbed
(eBay-Angebote fehlen dann einfach, kein Fehler).

1. Gehe zu [developer.ebay.com](https://developer.ebay.com) und registriere dich
   kostenlos.
2. **My Account -> Application Keys** -> im **Production**-Bereich ein neues
   Keyset erstellen.
3. Kopiere **App ID (Client ID)** und **Cert ID (Client Secret)**.

### 4. Supabase-Datenbank einrichten
1. Gehe zu [supabase.com](https://supabase.com) -> **Continue with GitHub** ->
   **New project** (Region **Central EU/Frankfurt** waehlen, wichtig fuers
   spaetere Dashboard-Tempo).
2. **SQL Editor -> New query** -> Inhalt von [scripts/init_db.sql](scripts/init_db.sql)
   einfuegen -> **Run**.
3. Zusaetzlich [scripts/add_dashboard_read_policy.sql](scripts/add_dashboard_read_policy.sql)
   ausfuehren (erlaubt dem Dashboard lesenden Zugriff).
4. **Project Settings -> API Keys**: kopiere die **Project URL**, den
   **Secret key** (`sb_secret_...`, fuer den Tracker selbst) und den
   **Publishable key** (`sb_publishable_...`, fuer das Dashboard — der ist
   bewusst oeffentlich/unbedenklich).

### 5. Projekt auf GitHub hochladen
```bash
git init
git add .
git commit -m "Initial commit: MacBook Preis-Tracker"
git branch -M main
git remote add origin https://github.com/DEIN-USERNAME/DEIN-REPO.git
git push -u origin main
```
Das Repository sollte **public** sein (Settings -> General -> Danger Zone ->
Change visibility) — private Repos haben nur 2.000 Freiminuten/Monat bei
GitHub Actions, was bei einem 30-Minuten-Cron schnell knapp wird. Keine
Geheimnisse liegen im Code, alle Keys stecken in GitHub Secrets.

### 6. Secrets in GitHub hinterlegen
**Settings -> Secrets and variables -> Actions -> New repository secret**,
jeweils einzeln:

| Name | Wert |
|---|---|
| `DISCORD_WEBHOOK_URL` | aus Schritt 1 |
| `GEMINI_API_KEY` | aus Schritt 2 (optional) |
| `EBAY_CLIENT_ID` | App ID aus Schritt 3 (optional) |
| `EBAY_CLIENT_SECRET` | Cert ID aus Schritt 3 (optional) |
| `SUPABASE_URL` | Project URL aus Schritt 4 |
| `SUPABASE_SERVICE_KEY` | Secret key aus Schritt 4 |

### 7. Dashboard verbinden und veroeffentlichen
1. Oeffne [dashboard/index.html](dashboard/index.html) und trage `SUPABASE_URL`
   sowie den **Publishable Key** (nicht den Secret Key!) in die beiden
   Konstanten am Anfang des `<script>`-Blocks ein.
2. **Settings -> Pages** -> Source: **Deploy from a branch** -> Branch `main`,
   Ordner `/ (root)` -> **Save**. Die Seite ist danach unter
   `https://DEIN-USERNAME.github.io/DEIN-REPO/dashboard/` erreichbar.
3. Passe bei Bedarf `DASHBOARD_URL` in `tracker/config.py` an diese URL an
   (wird in jede Discord-Nachricht als Link eingebaut).

### 8. Tracker aktivieren
- Der Workflow unter `.github/workflows/price_tracker.yml` startet automatisch
  alle 30 Minuten (GitHub Actions Cron-Schedule).
- Manuell testen: Im Repository auf **Actions** -> **MacBook Price Tracker** ->
  **Run workflow** klicken.

## Lokal testen
```bash
pip install -r requirements.txt
cp .env.example .env
# .env oeffnen und die Werte aus den Schritten oben eintragen
python price_tracker.py
```

## Wie Discord-Nachrichten aussehen
- **Neue Angebote**: eine Nachricht mit einem Feld pro Angebot (Preis, Quelle,
  Qualitaetsstufe, anklickbarer Titel, KI-Begruendung), Link zum Dashboard,
  und im Footer die Anzahl Angebote je Quelle plus die KI-Marktschaetzung. Ist
  ein Top-Deal/Schnaeppchen dabei, wird zusaetzlich `@everyone` gepingt.
- **Tages-Check-in** (einmal taeglich, unabhaengig von neuen Funden): kompakte
  Uebersicht mit guenstigstem Preis und Quellen-Aufschluesselung je Produkt,
  plus Dashboard-Link — damit der Link auch an ruhigen Tagen im Kanal auftaucht.

## Produkte anpassen (aktuell nur ueber die Datenbank)
Der Tracker verwaltet Produkte in der `products`-Tabelle in Supabase (Name,
Suchbegriff-Varianten, Preisgrenzen, aktive Quellen). Aktuell gibt es dafuer
noch keinen Discord-Bot mit `/track`-Befehl — neue Produkte koennen direkt im
Supabase **Table Editor** eingetragen werden. Beim allerersten Lauf legt der
Tracker automatisch ein Standard-Produkt (das MacBook oben) an, falls die
Tabelle noch leer ist.

## Bekannte Einschraenkung: Back Market
Back Market blockiert Anfragen von GitHub-Actions-IPs kategorisch mit HTTP 403
(IP-Reputations-Sperre) und bietet keine offizielle API fuer diesen
Anwendungsfall an. Deshalb ist Back Market bewusst nicht als Quelle enthalten
— es gibt hier keinen sauberen Fix ohne Anti-Bot-Umgehungstools, die dieses
Projekt nicht einsetzt.

## Hinweis zu den Scrapern
Die Suchergebnis-Seiten von Kleinanzeigen.de und refurbed koennen sich
jederzeit aendern (HTML-Struktur, Klassennamen) — eBay laeuft dagegen ueber die
offizielle Browse-API und ist davon nicht betroffen. Falls ein HTML-Scraper
irgendwann keine Treffer mehr liefert, muessen die CSS-Selektoren im
jeweiligen `SiteSpec`-Eintrag in `tracker/scrapers.py` an die aktuelle
Seitenstruktur angepasst werden. Ein Ausfall einzelner Quellen bricht den
Tracker nicht ab — die anderen werden trotzdem ausgewertet.
