# SchichtLohn

Preisrechner für 3D-Drucke. Läuft im Browser, ohne eigenes Konto.

**Öffnen:** https://schichtlohn.pages.dev/ (alternativ https://mitkiprogrammieren.github.io/Schichtlohn/)

## Funktionen

- **Rechner:** Drucker, Material, Verkaufskanal und Zahlungsart wählen, Aufschlag einstellen, Preis runden (z. B. auf ,90). Zeigt Verkaufspreis, Gewinn, Marge und die Aufteilung der Kosten.
- **Datei-Import:** `.gcode.3mf` und `.3mf` aus Bambu Studio oder Orca Slicer (Druckzeit, Gewicht je Filament, Vorschaubild), `.gcode`, sowie `.stl` und ungeslicte `.3mf` als Schätzung über das Volumen.
- **Portfolio:** häufige Produkte mit Bild, Gewicht und Druckzeit speichern.
- **Aufträge:** Status vom Angebot bis zur Bezahlung verfolgen.
- **Lager:** eigene Ansicht im Schichtlohn-Design für das FilamentLager aus Home Assistant (`todo.filament`): Suche, Sortierung, Filter, Sorten anlegen und bearbeiten, Rollen +/−, Reste, offene Verbräuche und AMS-Fächer zuordnen, dazu Waage und Druckbrücke. Mit Scannen und Serienscan (Kamera im Browser oder Scanner der HA-App), Filamentrollen mit Oberflächen (matt, Seide, Fasern, transparent …), Gramm-Anzeige der Waage, AMS-Feuchte mit Silica-Verlauf, Verbrauchsstatistik und Übernahme aus dem AMS. Liest und schreibt nur die HA-Daten. Unter Einstellungen → Lager lässt sich stattdessen die originale Karte anzeigen.
- **Druckaufträge:** fertige Drucke aus dem Home-Assistant-Druckprotokoll und der Bambu-Cloud-Historie übernehmen, auch mehrere in einen Auftrag.
- **Geschäft:** Umsatz und Gewinn je Monat, Bestseller.
- **PDF-Angebot** und **JSON-Backup**.

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
