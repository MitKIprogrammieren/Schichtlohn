# Formwerk

Großformat-Generator im Bambu-Studio-Look – ein Nachbau der LuBan-3D-Kernfunktionen in Rust.
Läuft als Web-App (z. B. auf dem Proxmox-NUC) und im Browser auf Mac, iPhone und Windows.

## Modi

| Modus | Eingabe | Ergebnis |
|---|---|---|
| Lithophane | Foto | Lithophane, positiv/negativ, Rand, glatte Seite vorn; große Bilder werden in Kacheln fürs Druckbett geteilt |
| Foto-Relief | Foto | Höhenrelief (hell = hoch) mit Sockel und Rand |
| Relief | 3D-Modell | 2,5D-Relief aus Richtung ±X/±Y/±Z, Sockel, Rand, „Begraben“, Negativ |
| Teilen | 3D-Modell | Zerlegung nach Bauraum, Dübeltaschen, Montagereihenfolge, mehrere Drucker nach Tempo |
| Stack | 3D-Modell | Schichten aus Plattenmaterial, Ringe, Dübellöcher, Gravur der nächsten Schicht, Teilung zu großer Konturen, Verschachtelung auf Bögen |
| Hash | 3D-Modell | Gesteckte X- und Z-Scheiben mit Schlitzen, Toleranz für Laser/Druck |
| Wireframe | 3D-Modell | Drahtgitter aus X/Y/Z-Schnittkurven |

Ausgabe: Bambu-3MF mit mehreren Platten, STL je Teil, SVG und DXF für den Laser
(rot = schneiden, blau = gravieren, schwarz = Beschriftung), `montage.txt`, `duebel.stl`.

Eingabe: JPG, PNG, WebP, BMP, GIF bzw. STL, 3MF, OBJ.

## Starten

```bash
docker compose up -d --build
# → http://<server>:8097
```

Ohne Docker:

```bash
cargo run --release
# Port und Datenordner: PORT=8097 FORMWERK_DATA=./data
```

Ergebnisse liegen 24 Stunden unter `data/jobs/` und werden danach gelöscht.

## Aufbau

- `src/mesh.rs` – Dreiecksnetz, Laden von STL/OBJ/3MF, STL schreiben
- `src/heightmap.rs` – Höhenfelder (Lithophane/Relief) als geschlossene Körper, Kacheln
- `src/section.rs` – Ebenenschnitte, Teilen mit geschlossenen Schnittflächen, Dübeltaschen
- `src/werk.rs` – die Generatoren
- `src/export.rs` – Platten packen, Bambu-3MF, SVG/DXF, Bögen verschachteln
- `src/main.rs` – Web-Server (axum)
- `static/index.html` – Oberfläche mit 3D-Vorschau (three.js, lokal eingebunden)
