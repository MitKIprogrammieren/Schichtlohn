# Gridwerk – Gridfinity-Generator

Web-App auf dem Proxmox-NUC (Port 8099) für das ganze Gridfinity-System:

- **Etiketten** – Clip-Etiketten (Pred-Stil, nach dem Generator von Laurens Guijt) mit Icons für Schrauben (inkl. Würth AW/RW), Muttern, Scheiben, Elektronik, Werkzeug, eigenem Text, eigenem Logo und QR-Code. Etikett und Schrift sind getrennte Teile → zwei Farben in Bambu Studio.
- **Behälter** – Bins mit Fächern, Griffmulde, Stapelrand, Magnet-/Schraublöchern und Clip-Halter für die Etiketten (nach 3DLG / gridfinity-rebuilt). Etiketten lassen sich je Fachreihe zuordnen.
- **Schublade** – Grundplatten nach Schubladen-Innenmaß mit Randausgleich, automatisch aufs Druckbett geteilt, plus Planer zum Einsetzen der Behälter.

Export als Bambu-Studio-3MF (Teile mit Filament 1/2) oder STL.

## Aufbau

- `src/` – Quellcode (`labels.js`, `bins.js`, `platten.js`, `ui_extra.js`, `app.html`)
- `build.py` – baut daraus `index.html` (eine Datei)
- `index.html` – wird vom NUC über jsDelivr geladen (fest auf den neuesten Commit, alle 10 Minuten geprüft)
- `server.py` – kleiner Server im Stack `gridwerk`: liefert die Seite aus, speichert die Liste unter `/daten/liste.json`, leitet QR-Kurzlinks `/q/<code>` weiter

Nach Änderungen in `src/` immer `python3 gridwerk/build.py` ausführen und `index.html` mit committen.
