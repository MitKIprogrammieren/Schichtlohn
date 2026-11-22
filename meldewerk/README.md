# Meldewerk

Eigener WhatsApp-Benachrichtigungsdienst auf dem NUC. Läuft als verknüpftes Gerät (wie WhatsApp Web) an einer zweiten Nummer und schickt Meldungen nur an dich.

- Oberfläche: `http://192.168.1.30:8077` – Verbindung (QR-Code), Testnachricht, Verlauf, Einstellungen
- Verlauf bleibt im Meldewerk gespeichert, auf dem Absender-Handy wird jede Nachricht gleich wieder gelöscht und der Chat archiviert

## Meldung schicken

Schlüssel steht in der Oberfläche unter Einstellungen → Schnittstelle.

```
GET  /api/senden?schluessel=…&quelle=sl&text=Druck%20fertig
POST /api/senden   (Kopfzeile X-Schluessel: …)
     {"quelle": "ha", "titel": "Druck fertig", "text": "P2S · Halterung", "bild": "http://…/kamera.jpg"}
```

`bild` darf eine Adresse oder ein `data:`-Bild sein. Ist WhatsApp gerade nicht verbunden, wartet die Meldung und wird nachgeschickt.

SchichtLohn schickt seine Druck- und Lager-Meldungen von selbst, wenn unter Einstellungen → Meldungen → WhatsApp Adresse und Schlüssel eingetragen sind.

## Aus Home Assistant

In Automationen das Skript **Meldewerk senden** (`script.meldewerk_senden`) aufrufen – Felder Titel, Text und optional Kamera oder Bild. Das Skript löst das Ereignis `meldewerk_senden` aus, auf das das Meldewerk hört (dafür `HA_URL` und `HA_TOKEN` in der .env). Kein YAML, kein Neustart nötig.

## Installation (Schaltwerk)

Stack `meldewerk` mit `compose.yaml` aus diesem Ordner anlegen. Der Container holt sich die Programmdateien beim Start aus dem Repo – ein Update ist einfach ein Neustart des Stacks.
