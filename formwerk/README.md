# Formwerk

Zerlegt große 3D-Modelle so, dass jedes Teil auf das Druckbett passt – im Bambu-Studio-Look,
angelehnt an „Mesh → Cut“ aus LuBan 3D. Läuft als Web-App (z. B. auf dem Proxmox-NUC) und im
Browser auf Mac, iPhone und Windows.

- Eingabe: STL, 3MF oder OBJ
- Schnitt nach Bauraum, auch für mehrere Drucker (Teile werden nach Tempo verteilt)
- Verbinder: Dübel rund/eckig, Steckzapfen rund/eckig, Kegelzapfen, Magnettaschen
- Ausgabe: Bambu-3MF mit mehreren Platten, STL je Teil, `montage.txt`, `duebel.stl`

## Starten

```bash
docker compose up -d --build
# → http://<server>:8097
```

Ohne Docker: `cargo run --release` (Port und Datenordner: `PORT=8097 FORMWERK_DATA=./data`).
Ergebnisse liegen 24 Stunden unter `data/jobs/` und werden danach gelöscht.

## Aufbau

- `src/mesh.rs` – Dreiecksnetz, Laden von STL/OBJ/3MF, STL schreiben
- `src/section.rs` – Ebenenschnitte, geschlossene Schnittflächen, Taschen und Zapfen
- `src/werk.rs` – Teilen, Verbinder, Druckerzuteilung, Montagereihenfolge
- `src/export.rs` – Platten packen, Bambu-3MF, ZIP
- `src/main.rs` – Web-Server (axum)
- `static/index.html` – Oberfläche mit 3D-Vorschau (three.js, lokal eingebunden)
