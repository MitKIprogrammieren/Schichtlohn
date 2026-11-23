# Formwerk

**Druckvorbereitung fürs Handy** (Startseite `/`) – nach dem Vorbild der App „Druckvorbereitung“:

1. **Modell** – Drucker wählen (eigene Bambu-, Snapmaker- und Creality-Drucker oder eigene Maße), STL/3MF/OBJ öffnen
   (mehrfarbige 3MF behalten Teile, Filamente und Bemalung), Favoriten auf dem Gerät, **Selbst gestalten**:
   Vorlagen mit Maßen, Schild & QR, Lithophane und Logo aus Bild, Zeichnen mit dem Finger, Modellsuche
2. **Anpassen** – 3D-Druckbett, Größe, Drehen, Flach hinlegen, Anzahl, **Bett füllen**, automatisch auf mehrere Platten,
   Farbe je Teil, **Bereiche einfärben**, Farbwechsel ab Höhe, Platz für den Reinigungsturm, Zerlegen zu großer Modelle
3. **Drucken** – Druck-Check (beste Drucklage, Stützen, Rand, Farbwechsel, zu groß …), Schätzung von Zeit und Filament,
   Download als Bambu-3MF (Platten, Filament je Teil, Bemalung, Einstellungen je Objekt) oder STL je Platte

Die bisherige Desktop-Oberfläche zum Teilen großer Modelle liegt unter `/teilen`.

---

## Großformat teilen (`/teilen`)

Zerlegt große 3D-Modelle so, dass jedes Teil auf das Druckbett passt – im Bambu-Studio-Look,
angelehnt an „Mesh → Cut“ aus LuBan 3D. Läuft als Web-App (z. B. auf dem Proxmox-NUC) und im
Browser auf Mac, iPhone und Windows.

- Eingabe: STL, 3MF oder OBJ (Objekte eines 3MF werden einzeln behandelt)
- Originalgröße bleibt, Maßstab oder größte Kante auf Wunsch
- Was passt, wird nur angeordnet; zu große Objekte werden zuerst gedreht, dann Schritt für Schritt
  an der dünnsten Stelle geteilt – ohne Kleinteile, jedes Teil mit einer Schnittfläche nach unten
- Mehrere Drucker: Teile werden nach Tempo verteilt
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
- `src/prep.rs` – Druckvorbereitung: Laden mit Farben, Drucklagen, Bambu-3MF/STL-Ausgabe
- `src/main.rs` – Web-Server (axum)
- `static/druck.html`, `static/druck_app.js`, `static/druck_gestalten.js` – Handy-Oberfläche
- `static/index.html` – Oberfläche mit 3D-Vorschau (three.js, lokal eingebunden)
