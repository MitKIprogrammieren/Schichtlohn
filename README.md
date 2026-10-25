# Schichtlohn

Preisrechner für 3D-Drucke. Läuft komplett im Browser, ohne Server und ohne Konto.

**Öffnen:** https://mitkiprogrammieren.github.io/Schichtlohn/

## Funktionen

- **Rechner:** Drucker, Material, Verkaufskanal und Zahlungsart wählen, Aufschlag einstellen, Preis runden (z. B. auf ,90). Zeigt Verkaufspreis, Gewinn, Marge und die Aufteilung der Kosten.
- **Datei-Import:** `.gcode.3mf` und `.3mf` aus Bambu Studio oder Orca Slicer (Druckzeit, Gewicht je Filament, Vorschaubild), `.gcode`, sowie `.stl` und ungeslicte `.3mf` als Schätzung über das Volumen.
- **Portfolio:** häufige Produkte mit Bild, Gewicht und Druckzeit speichern.
- **Aufträge:** Status vom Angebot bis zur Bezahlung verfolgen.
- **Geschäft:** Umsatz und Gewinn je Monat, Bestseller.
- **PDF-Angebot** und **JSON-Backup**.

## Daten

In der GitHub-Pages-Version liegen alle Daten nur im Browser des jeweiligen Geräts (localStorage). Mit **Einstellungen → Backup exportieren / einspielen** überträgst du sie auf ein anderes Gerät oder in die Home-Assistant-Version.

## Aufs iPhone

In Safari öffnen, Teilen → „Zum Home-Bildschirm“. Schichtlohn startet dann wie eine App.

## Home Assistant

`homeassistant/schichtlohn-card.js` ist eine Lovelace-Karte (`custom:schichtlohn-card`).

1. Einstellungen → Dashboards → Ressourcen: `https://mitkiprogrammieren.github.io/Schichtlohn/homeassistant/schichtlohn-card.js` als **JavaScript-Modul** hinzufügen.
2. Ein Dashboard mit einer Ansicht vom Typ **Panel** anlegen und die Karte `type: custom:schichtlohn-card` einsetzen.

In Home Assistant werden die Daten im HA-Benutzerkonto gespeichert (auf allen Geräten gleich), und Materialien lassen sich aus dem FilamentLager (`todo.filament`) übernehmen.
