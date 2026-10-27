# FilamentLager in Bambuddy

Das Lager aus SchichtLohn, mit Bambuddys Inventar als Datenquelle und als Eintrag in Bambuddys Seitenleiste. Bambuddy bleibt unverändert und wird weiter ganz normal aktualisiert.

## Was es macht

- **Sorten statt Spulen:** Gleiche Spulen aus Bambuddy (Marke, Material, Variante, Farbe, Nenngewicht) erscheinen als eine Sorte mit Rollen und Resten – wie im SchichtLohn-Lager.
- **Bearbeiten wirkt in Bambuddy:** „+ Rolle“ legt eine Spule an (bzw. holt eine archivierte zurück), „− Rolle“ setzt eine Spule auf leer und archiviert sie, ein geänderter Rest ändert `weight_used`. Preis, Farbe, Düsentemperatur und Filamentprofil werden in allen Spulen der Sorte gespeichert, die übrigen Lager-Angaben im Notizfeld (`SL:{…}`).
- **Abbuchen:** Bambu-Drucke bucht Bambuddy nach Druckende selbst ab (aus der 3MF bzw. dem AMS), genau einmal auf dem Server. Der Verlauf erscheint in der Lager-Statistik. Creality-Drucke aus der Creality-Cloud bucht SchichtLohn wie bisher ab, nur eben in Bambuddy.
- **AMS:** Ort im AMS, „Fächer ohne Zuordnung“ und AMS-Feuchte kommen live aus Bambuddys Druckerstatus.
- **Automatische Fach-Zuordnung:** Bambuddy bucht nur von Spulen ab, die einem AMS-Fach zugeordnet sind. Ist ein belegtes Fach noch ohne Zuordnung, ordnet das Lager eine passende Spule zu (gleiches Filamentprofil, fast gleiche Farbe; angebrochene bzw. die zum Füllstand passende zuerst). Fächer mit Generic-Profil oder ohne passende Sorte bleiben unter „Fächer ohne Zuordnung“. Das passiert, solange das Lager irgendwo geöffnet ist. In Bambuddy „Unbekannte RFID-Spulen automatisch hinzufügen“ ausschalten, sonst entstehen doppelte Spulen.
- „Nicht zugeordnet“ und die Lager-Einstellungen liegen im Browser.

## Einrichten auf der Synology (Bambuddy und Lager zusammen)

Die Datei `synology/docker-compose.yml` enthält das Original-Bambuddy und das Lager. Das Lager holt sich seine Dateien bei jedem Start selbst von GitHub, auf der NAS ist kein `git` nötig.

1. **Ordner anlegen:** File Station → Freigabe `docker` → neuer Ordner `bambuddy`.
2. **Projekt anlegen:** Container Manager → Projekt → Erstellen
   - Projektname: `bambuddy`
   - Pfad: `/docker/bambuddy`
   - Quelle: „docker-compose.yml erstellen“ und den Inhalt von [`synology/docker-compose.yml`](synology/docker-compose.yml) einfügen
   - Weiter, Web-Portal-Einstellungen überspringen, Fertig. Die Images werden geladen und gestartet.
3. **Bambuddy öffnen:** `http://<NAS-IP>:8000` und die Drucker hinzufügen (IP-Adresse, Seriennummer, Zugangscode – am Drucker unter Einstellungen → Netzwerk bzw. Geräteinfo). Feste IP-Adressen für die Drucker in der FritzBox vergeben.
4. **Lager einhängen:** in Bambuddy Einstellungen → Externe Links → Neuer Link, Name `FilamentLager`, URL `http://<NAS-IP>:8091/`, Icon `package`, „In neuem Tab öffnen“ aus.
5. **Bambu Studio:** im Reiter Gerät bei jedem Drucker „Gesendete Dateien auf externem Speicher ablegen“ einschalten, damit Bambuddy die 3MF (Gramm je Filament, Vorschaubild) bekommt.

**Drucker bleiben in der Cloud** (kein LAN-only, kein Developer Mode). Bambuddy liest dann nur mit und zeigt einen Hinweis zum Entwicklermodus – den kannst du ignorieren. Bambu Handy und Cloud-Druck funktionieren weiter.

**Testdruck:** Danach sollte der Druck in Bambuddys Archiv mit Vorschaubild und Gramm erscheinen und die Spule im Lager weniger werden. Fehlt die 3MF, bucht Bambuddy über den Füllstand im AMS ab – das klappt nur bei Spulen, für die das AMS einen Füllstand meldet (z. B. Bambu-Spulen mit RFID).

**Wenn das Lager „Bambuddy nicht erreichbar“ meldet:** im Projekt die `docker-compose.yml` bearbeiten, bei `BAMBUDDY_URL` die IP der NAS eintragen (z. B. `http://192.168.1.20:8000`) und das Projekt neu erstellen. Ist die Synology-Firewall an, die Ports 8000 und 8091 im Heimnetz erlauben.

**Aktualisieren:**
- Lager: Projekt stoppen und starten.
- Bambuddy: Container Manager → Image → `ghcr.io/maziggy/bambuddy` → Aktualisieren, danach Projekt neu starten.

## Einrichten auf einem Linux-Server, auf dem Bambuddy schon läuft

```bash
git clone https://github.com/MitKIprogrammieren/Schichtlohn.git
cd Schichtlohn/bambuddy
docker compose up -d
```

Danach im Browser `http://<server>:8091/` öffnen – das ist das Lager. Die ganze SchichtLohn-App (mit Rechner, Aufträgen …) liegt unter `http://<server>:8091/index.html`.

**In Bambuddy einhängen:** Einstellungen → Externe Links → Neuer Link
- Name: `FilamentLager`
- URL: `http://<server>:8091/`
- Icon: `package`
- „In neuem Tab öffnen“: aus (dann zeigt Bambuddy das Lager direkt in seiner Oberfläche)

### Wenn in Bambuddy die Anmeldung eingeschaltet ist

In Bambuddy unter Einstellungen → API-Schlüssel einen Schlüssel mit „Status lesen“ und „Inventar verwalten“ anlegen und in `docker-compose.yml` bei `BAMBUDDY_API_KEY` eintragen, dann `docker compose up -d`. Der Schlüssel bleibt im Container.

Ohne Anmeldung in Bambuddy kann jeder im Heimnetz, der Port 8091 erreicht, das Inventar ändern – genauso wie in Bambuddy selbst.

### Andere Adresse von Bambuddy

Läuft Bambuddy nicht auf demselben Rechner bzw. nicht auf Port 8000, `BAMBUDDY_URL` anpassen (z. B. `http://192.168.178.20:8000`).

## Aktualisieren

- **Bambuddy:** wie gewohnt (`docker compose pull && docker compose up -d` im Bambuddy-Ordner).
- **Lager/SchichtLohn:** `cd Schichtlohn && git pull` – der Container liefert die neuen Dateien sofort aus, ein Neustart ist nicht nötig.

## Technik

- `docker-compose.yml`: nginx (offizielles Image), liefert dieses Repo aus und leitet `/api/` samt WebSocket an Bambuddy weiter. So laufen Lager und Bambuddy-API über dieselbe Adresse; Bambuddy erlaubt keine Aufrufe von fremden Adressen (kein CORS).
- `nginx.conf.template`: setzt beim Ausliefern `window.SL_BAMBUDDY` in `index.html` – nur dann arbeitet SchichtLohn im Bambuddy-Modus. Auf schichtlohn.pages.dev und GitHub Pages ändert sich nichts.
- `adapter.js`: Übersetzung zwischen Lager-Sorten und Bambuddy-Spulen (`/api/v1/inventory/spools`, `/inventory/usage`, `/printers/{id}/status`, WebSocket `/api/v1/ws`).
