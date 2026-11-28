# Formwerk

**Druckvorbereitung fürs Handy** (Startseite `/`) – nach dem Vorbild der App „Druckvorbereitung“:

1. **Modell** – Drucker wählen (eigene Bambu-, Snapmaker- und Creality-Drucker oder eigene Maße), STL/3MF/OBJ öffnen
   (mehrfarbige 3MF behalten Teile, Filamente und Bemalung), Favoriten auf dem Gerät, **Selbst gestalten**:
   Vorlagen mit Maßen, Schild & QR, Lithophane und Logo aus Bild, Zeichnen mit dem Finger, Modellsuche
2. **Anpassen** – 3D-Druckbett, Größe, Drehen, Flach hinlegen, Anzahl, **Bett füllen**, automatisch auf mehrere Platten,
   Farbe je Teil, **Bereiche einfärben**, Farbwechsel ab Höhe, Platz für den Reinigungsturm, Zerlegen zu großer Modelle
3. **Drucken** – Druck-Check (beste Drucklage, Stützen, Rand, Farbwechsel, zu groß …), Schätzung von Zeit und Filament,
   Download als Bambu-3MF (Platten, Filament je Teil, Bemalung, Einstellungen je Objekt) oder STL je Platte

## Teilen (`/teilen`) – nach dem Vorbild von ModelSplitter

Modelle frei zerteilen, mit Verbindern und eingravierten Nummern (Desktop/Tablet, läuft auf dem Server):

- **Schnittwerkzeuge:** Band (auf ein Glied klicken – Formwerk sucht die schmalste Stelle quer herum, kippen/verschieben),
  Bemalen (Stück anmalen, der Pinsel wirkt durch das ganze Glied), Linie (in Blickrichtung, nur was die Linie überquert),
  Ebene (X/Y/Z, Lage, zwei Kippwinkel), Mehrfach (gleichmäßig je Achse), Auto (möglichst wenige Stücke fürs Druckbett)
- Band, Bemalen und Linie trennen nur die getroffene Stelle ab – der Rest des Modells bleibt ganz.
  Überlappende Körper (Figuren aus mehreren Teilen) bleiben bei dem Stück, mit dem sie sich überlappen.
- **Verbinder:** fester Zapfen, loser Zapfen (als eigenes Druckteil), Magnet (Ø × Höhe), Steckzapfen, keiner;
  Formen rund, Vierkant, Kegel-Vierkant, Kreuz, Stern, Sechskant; Spiel, Durchmesser und Anzahl einstellbar.
  Zapfen werden nur gesetzt, wo das Teil dick genug ist.
- **Nummern:** Fugennummer in beide Schnittflächen eingraviert (oben gespiegelt, damit von außen lesbar)
- Rückgängig (30 Schritte), Teile umbenennen, Explosionsansicht, Nummern in der Ansicht
- **Export:** Bambu-3MF mit Platten (Teile mit Schnittfläche nach unten), STL je Teil als ZIP,
  Montage-PDF (Übersicht + ein Bild je Fuge), Projekt als 3MF (lässt sich mit allen Fugen wieder öffnen)
- **Farben:** bemalte 3MF aus Bambu Studio, Orca oder PrusaSlicer öffnen – jede gemalte Fläche wird ein festes Teil
  mit einstellbarer Tiefe, der Grundkörper bekommt passende Taschen. Zwei Arten:
  *Zum Einstecken* (jedes Teil einfarbig einzeln drucken, mit Spiel, Sichtseite unten) oder
  *Im Objekt (AMS)* (ein Objekt mit passgenauen Teilen je Filament). Kleine Flecken lassen sich weglassen,
  gleiche Farben zu einem Teil zusammenfassen. An dünnen Wänden werden die Farbteile automatisch flacher.
  Mehrteilige 3MF: unbemalte Teile in anderer Farbe werden direkt eigene Teile.
- STEP wird noch nicht gelesen (bitte als STL/3MF speichern)

Die frühere Oberfläche liegt unter `/teilen/klassisch`.

---

## Großformat teilen (`/teilen/klassisch`)

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
- `src/werk.rs` – Teilen, Verbinder, Druckerzuteilung, Montagereihenfolge (klassisch)
- `src/schnitt.rs` – freie und örtliche Schnitte, Verbinderformen, Nummern, Sitzungen mit Rückgängig
- `src/farben.rs` – Bemalung lesen (TriangleSelector-Format), Farbflächen zu Teilen mit Taschen
- `src/teilen_api.rs` – Schnittstelle der Teilen-Seite
- `static/teilen.html`, `static/teilen_app.js` – Teilen-Oberfläche inkl. Montage-PDF
- `src/export.rs` – Platten packen, Bambu-3MF, ZIP
- `src/prep.rs` – Druckvorbereitung: Laden mit Farben, Drucklagen, Bambu-3MF/STL-Ausgabe
- `src/main.rs` – Web-Server (axum)
- `static/druck.html`, `static/druck_app.js`, `static/druck_gestalten.js` – Handy-Oberfläche
- `static/index.html` – Oberfläche mit 3D-Vorschau (three.js, lokal eingebunden)
