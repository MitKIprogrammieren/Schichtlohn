# ModelBrowser

Private Web-Dateiverwaltung für 3D-Druckmodelle (MakerWorld, Printables, Cults 3D, 3D Sets, YouMagine …) auf dem Proxmox-NUC.

- Link einfügen oder per iOS-Kurzbefehl teilen → Seite wird mit SingleFile gespeichert, Bilder und Infos ausgelesen
- MakerWorld-Konto: 3MF der Druckprofile automatisch laden, STL daraus erzeugen
- 3D-Ansicht, Notizen, Status, eigene Fotos, Suche, ZIP, Update-Hinweis, PIN-Anmeldung
- 3D Sets: nie automatische Downloads

## Dateien
- `server.py` – Python-Server (nur Standardbibliothek, braucht Chromium + single-file-cli im Image)
- `index.html` – Oberfläche
- `start.py` – Starter auf dem NUC: holt beide Dateien über jsDelivr vom neuesten Commit und startet den Server

Daten, Konten und PIN liegen nur auf dem NUC unter `/daten`, nie im Repo.

## Update
Änderung pushen, dann den Stack `modelbrowser` neu starten.
