# Konturwerk

Werkzeug-Umrisse aus einem Foto → Gridfinity-Einsatz oder freie Platte, optional mit **TPU-Inlay**.
Nachbau der Tooltrace-Kernfunktionen in Rust, Oberfläche im Bambu-Studio-Look. Läuft als Web-App
(Proxmox-NUC) und im Browser auf Mac, iPhone und Windows.

## Ablauf

1. **Foto** – Werkzeuge auf ein weißes Blatt (A4, A3, A5, Letter, Legal) legen, von oben fotografieren.
2. **Umrisse** – Blatt wird gefunden und entzerrt (1 mm = 4 Pixel), Werkzeuge werden als Umrisse in mm erkannt.
   Nachbessern per Rahmen oder Antippen, Umrisse in der Bibliothek speichern.
3. **Anordnen** – Werkzeuge ziehen, drehen, spiegeln, Fingermulden, Rechtecke, Langlöcher. Raster und Höhe
   passen sich automatisch an.
4. **Export** – Bambu-3MF, STL je Teil, SVG und DXF (Laser/Schaumstoff), 3D-Vorschau mit Schnitt.

## Erkennung

| Modus | Wie |
|---|---|
| Klassisch | Blatt per Helligkeit finden, Kanten mit Ausgleichsgeraden, Homographie; Hintergrund als Fläche geschätzt; zweistufige Schwelle (dunkel oder farbig), Löcher füllen, Subpixel-Kontur |
| KI | Freistell-Modell lokal über ONNX Runtime: **Schnell** (U²-Net klein, 5 MB) oder **Genau** (IS-Net, 170 MB). Ganzes Blatt + jedes Werkzeug im Ausschnitt; deutlich erkannte Bereiche aus der klassischen Erkennung bleiben erhalten (z. B. blanker Stahl) |

Modelle werden beim ersten Gebrauch nach `data/modelle/` geladen. Fehlt die KI, wird klassisch erkannt.

## TPU-Inlay

| Variante | Ergebnis |
|---|---|
| Aus | Taschen direkt im Behälter |
| Separat | Flache Schale (PLA/PETG) + TPU-Einsatz mit den Taschen, zwei Platten in der 3MF, Spiel einstellbar |
| Kombiniert | Ein Objekt, zwei Teile: Schale Filament 1, TPU-Einsatz Filament 2 – ein Druck mit AMS/H2C |

Taschen, die fast bis zum Boden des Inlays reichen (weniger als „TPU unter Tasche“), werden durchgebrochen.

## Gridfinity

42-mm-Raster, Höhe in 7-mm-Einheiten, Fußprofil 0,8 / 1,8 / 2,15 mm, optional Magnetlöcher 6,5 × 2,4 mm
und Stapelrand. Alle Körper sind wasserdichte Netze.

## Starten

```bash
docker compose up -d --build
# → http://<server>:8089
```

Ohne Docker (KI braucht `libonnxruntime.so` 1.22):

```bash
ORT_DYLIB_PATH=/pfad/libonnxruntime.so cargo run --release
# Port und Datenordner: PORT=8089 KONTURWERK_DATA=./data
```

Daten: `data/jobs/` (7 Tage), `data/modelle/`, `data/bibliothek.json`.

## Aufbau

- `src/erkennung.rs` – Blatt finden, entzerren, Objektkarte, Schwellen, Konturen
- `src/ki.rs` – ONNX-Modelle laden und ausführen
- `src/behaelter.rs` – Gridfinity-Behälter, Platte, Taschen, TPU-Inlay
- `src/netz.rs` – Stufenkörper (2,5D), Lofts, wasserdichte Netze, STL
- `src/export.rs` – Bambu-3MF, SVG, DXF
- `static/index.html` – Oberfläche (eine Datei, three.js für die Vorschau)
