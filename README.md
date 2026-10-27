# SchichtLohn

Preisrechner für 3D-Drucke. Läuft im Browser, ohne eigenes Konto.

**Öffnen:** https://schichtlohn.pages.dev/ (alternativ https://mitkiprogrammieren.github.io/Schichtlohn/)

## Funktionen

- **Rechner:** Drucker, Material, Verkaufskanal und Zahlungsart wählen, Aufschlag einstellen, Preis runden (z. B. auf ,90). Zeigt Verkaufspreis, Gewinn, Marge und die Aufteilung der Kosten.
- **Datei-Import:** `.gcode.3mf` und `.3mf` aus Bambu Studio oder Orca Slicer (Druckzeit, Gewicht je Filament, Vorschaubild), `.gcode`, sowie `.stl` und ungeslicte `.3mf` als Schätzung über das Volumen.
- **Portfolio:** häufige Produkte mit Bild, Gewicht und Druckzeit speichern.
- **Aufträge:** Status vom Angebot bis zur Bezahlung verfolgen.
- **Lager:** eigene Ansicht im Schichtlohn-Design für das FilamentLager aus Home Assistant (`todo.filament`): Suche, Sortierung, Filter, Sorten anlegen und bearbeiten, Rollen +/−, Reste, offene Verbräuche und AMS-Fächer zuordnen, dazu Waage und Druckbrücke. Mit Scannen und Serienscan (Kamera im Browser oder Scanner der HA-App), Filamentrollen mit Oberflächen (matt, Seide, Fasern, transparent …), Gramm-Anzeige der Waage, AMS-Feuchte mit Silica-Verlauf, Verbrauchsstatistik und Übernahme aus dem AMS. Liest und schreibt nur die HA-Daten. Unter Einstellungen → Lager lässt sich stattdessen die originale Karte anzeigen. Ohne Home Assistant funktioniert das Lager auch direkt im Browser (ohne AMS, Feuchte, Waage und Druckbrücke); die Daten liegen dann nur auf diesem Gerät und kommen mit dem Backup mit.
- **Druckaufträge:** fertige Drucke aus dem Home-Assistant-Druckprotokoll und der Bambu-Cloud-Historie übernehmen, auch mehrere in einen Auftrag.
- **Geschäft:** Umsatz und Gewinn je Monat, Bestseller.
- **PDF-Angebot** und **JSON-Backup**.

## SchichtLohn-Server (Synology)

Ein Container für die Synology mit einer Datenbank (SQLite) für Lager, Verbrauch, Einstellungen, Portfolio und Aufträge. Mac, iPhone, Home Assistant und die Waage sehen damit denselben Stand; Änderungen erscheinen sofort auf allen offenen Geräten. Im selben Container läuft der Etikett-Leser für Spulenfotos.

**Einrichten (Container Manager):**

1. In File Station den Ordner `docker/schichtlohn` anlegen (dort liegt die Datenbank `schichtlohn.db`, Hyper Backup kann sie mitsichern).
2. Container Manager → Projekt → Erstellen, Name `schichtlohn`, „docker-compose.yml erstellen“, Inhalt aus [`server/docker-compose.yml`](server/docker-compose.yml) einfügen, fertigstellen.
3. Prüfen: `http://<synology>:8093/` zeigt `{"ok": true, "dienst": "schichtlohn-server", …}`.
4. In SchichtLohn: Einstellungen → SchichtLohn-Server → Adresse eintragen → **Daten übernehmen und Server verwenden**. Das kopiert Lager (`todo.filament`), Verbrauch und SchichtLohn-Daten aus Home Assistant bzw. diesem Browser auf den Server. Auf den weiteren Geräten nur die Adresse eintragen und **Nur verbinden** wählen.

Wird SchichtLohn über **https** geöffnet (schichtlohn.pages.dev, Home Assistant über Nabu Casa), muss der Server ebenfalls per https erreichbar sein: DSM → Systemsteuerung → Anmeldeportal → Erweitert → Reverse Proxy → Erstellen, Quelle `https` mit eigenem Hostnamen (z. B. `schichtlohn.name.synology.me`), Port 443, Ziel `http://localhost:8093`; Zertifikat unter Sicherheit → Zertifikat zuweisen. Ist der Server von außen erreichbar, in der Compose-Datei `TOKEN` setzen und den Schlüssel in SchichtLohn eintragen.

Schnittstelle (auch für die Waage): `GET /api/sorten`, `GET/POST /api/listen/<name>` (gleiches Format wie die To-do-Listen in HA), `GET/PUT /api/daten/<schlüssel>`, `GET /api/ereignisse` (Live-Meldungen), `GET /api/sicherung`, `POST /lesen` (Foto).

### Spule per Foto erkennen

Im Lager öffnet **Foto** die Kamera oder die Fotomediathek, auch mehrere Bilder auf einmal. Ein Barcode im Bild wird direkt gelesen, den Etikett-Text liest der Server (PaddleOCR-Modelle über RapidOCR, lokal, ohne Cloud). Danach im Foto aufs Filament tippen, um die Farbe festzulegen, und aus den Vorschlägen aus Lager und Filament-Datenbank wählen. Gibt es zur Sorte einen EAN, wird er bei der Sorte gespeichert; ab dann erkennt der Scanner den Karton.

Das Container-Image wird per GitHub Action für x86 und ARM gebaut (`ghcr.io/mitkiprogrammieren/schichtlohn-server`).

## Creality-Cloud

Unter **Einstellungen → Creality-Cloud** verbindest du dein Creality-Konto, am sichersten per QR-Code mit Bestätigung in der Creality-Cloud-App (zweiter Faktor, ohne Passwort), alternativ mit E-Mail und Passwort (wird nicht gespeichert). Dann zeigt SchichtLohn im Reiter **Druckaufträge** den Status deiner Creality-Drucker (Fortschritt, Restzeit, Temperaturen, CFS-Farben) und die Druckhistorie. Fertige Drucke seit dem Verbinden werden einmal im Lager abgebucht; ohne passende Sorte landen sie unter „Nicht zugeordnet“. Beides lässt sich in den Einstellungen abschalten. Der Abruf läuft über `functions/creality/` auf schichtlohn.pages.dev, speichert nichts und nutzt eine inoffizielle Schnittstelle.

## Quellen

Die Liste der Filamentmarken und -sorten im Rechner (Marke, Material, Variante, Dichte) stammt aus [SpoolmanDB](https://github.com/Donkie/SpoolmanDB) (MIT-Lizenz).

Der Scanner im Lager nutzt `filamentdb.json`, gebaut aus der [Open Filament Database](https://github.com/OpenFilamentCollective/open-filament-database) und SpoolmanDB (beide MIT-Lizenz): rund 19 000 Farben von knapp 200 Marken, davon etwa 6000 mit Barcode (EAN/GTIN). Ein Code aus der Datenbank wird beim Scannen direkt erkannt; bei einem unbekannten Code (z. B. Amazon-Etikett X00…) sucht man die Sorte nach Marke, Linie und Farbe und legt sie mit diesem Code an. Die Datei wird jede Woche per GitHub Action neu gebaut (`tools/filamentdb.py`). Nach Änderungen an `index.html` baut `python3 tools/karte.py` die Home-Assistant-Karte neu. Preise für Bambu Lab sind EU-Listenpreise; bei den übrigen Sorten ist der Preis ein Richtwert je Materialart (mit ≈ markiert), bis du einen eigenen Preis einträgst oder die Sorte im Lager hast.

## Daten

In der GitHub-Pages-Version liegen alle Daten nur im Browser des jeweiligen Geräts (localStorage). Mit **Einstellungen → Backup exportieren / einspielen** überträgst du sie auf ein anderes Gerät oder in die Home-Assistant-Version.

## Aufs iPhone

In Safari öffnen, Teilen → „Zum Home-Bildschirm“. SchichtLohn startet dann wie eine App.

## Home Assistant

`homeassistant/schichtlohn-card.js` ist eine Lovelace-Karte (`custom:schichtlohn-card`).

1. Einstellungen → Dashboards → Ressourcen: `https://mitkiprogrammieren.github.io/Schichtlohn/homeassistant/schichtlohn-card.js` als **JavaScript-Modul** hinzufügen.
2. Ein Dashboard mit einer Ansicht vom Typ **Panel** anlegen und die Karte `type: custom:schichtlohn-card` einsetzen.

In Home Assistant werden die Daten im HA-Benutzerkonto gespeichert (auf allen Geräten gleich), und Materialien lassen sich aus dem FilamentLager (`todo.filament`) übernehmen.

### Druckprotokoll

Eine Automation schreibt jeden beendeten oder abgebrochenen Druck in die To-do-Liste `todo.druckprotokoll` (Drucker, Aufgabe, Start, Ende, Gramm je AMS-Fach mit Material und Farbe). SchichtLohn zeigt diese Drucke im Reiter **Druckaufträge**; übernommene Einträge werden in der Liste abgehakt.

## Bambu-Cloud

Unter **Einstellungen → Bambu-Cloud** meldest du dich mit deinem Bambu-Lab-Konto an (E-Mail, Passwort, Bestätigungscode). Das Passwort wird nicht gespeichert, nur der Anmeldeschlüssel im Browser. Weil die Bambu-API keine Aufrufe direkt aus dem Browser erlaubt, läuft der Abruf über `functions/bambu/` (Cloudflare Pages Function auf schichtlohn.pages.dev), die nur Anmeldung und Druckhistorie durchreicht und nichts speichert. Die Schnittstelle ist inoffiziell und kann sich ändern.
