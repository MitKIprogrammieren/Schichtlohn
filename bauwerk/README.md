# Bauwerk 2

Schlankes, parametrisches CAD in reinem Rust – aufgebaut wie SolidCraft:
ein Kern für **Mac-App**, **Browser (NUC)** und **MCP/Kommandozeile**.

- **Skizzen mit Bedingungen**: Linie, Rechteck (2 Ecken / Mitte), Kreis (Mittelpunkt / 3 Punkte), Bogen, Punkt;
  Bedingungen Deckend, Horizontal, Vertikal, Parallel, Senkrecht, Gleich, Tangential, Mittelpunkt, Symmetrisch, Fixieren;
  Bemaßungen (Länge, Abstand, Ø, Radius, Winkel). Der Löser zeigt „voll bestimmt“ / offene Freiheitsgrade / Widerspruch.
- **Parameter & Ausdrücke**: jedes Maß kann `breite/2 + wand` sein.
- **Zeitleiste** mit Zurückrollen, Features Extrudieren (Verbinden/Ausschneiden/Schnittmenge, Außenecken runden/fasen),
  Drehen, Bohrung (Durchgang, Einschmelzmutter, Senkkopf, Zylinderkopf).
- **Export** STL, 3MF, STEP (facettiert – echte Flächen über Mesh2STEP).
- Leichte Grafik: flache Flächen mit Kanten, gerendert wird nur bei Änderungen.

## Aufbau
```
crates/kern   Rust-Kern: Modell, Ausdrücke, Skizzen-Löser, Profile, Netze (boolmesh), Export
crates/cli    bauwerk: Server (Oberfläche + API + /mcp), MCP über stdio, run/pruefen
web/          Oberfläche (eine Seite, three.js lokal mitgeliefert)
app/          Mac-App (natives Fenster mit WebKit, Kern im selben Prozess)
```

## Mac
```
./scripts/mac-installieren.sh
```
Installiert `Bauwerk.app` und die Kommandozeile `~/.local/bin/bauwerk`. Projekte liegen in `~/Bauwerk`.

## NUC
Stack `bauwerk` (siehe `compose.yaml`), Daten unter `/opt/stacks/bauwerk/daten`. Projekte aus Bauwerk 1 werden
beim Öffnen automatisch umgewandelt.

## MCP
- Server/NUC: `http://192.168.1.30:8061/mcp`
- laufende Mac-App: `http://127.0.0.1:8765/mcp`
- stdio: `claude mcp add bauwerk -- bauwerk mcp`

Werkzeuge: `format_hilfe`, `projekte_liste`, `projekt_lesen`, `projekt_pruefen`, `projekt_schreiben`,
`parameter_setzen`, `exportieren` (STL/3MF/STEP – z. B. direkt als Eingabe für Mesh2STEP).

## Kommandozeile
```
bauwerk app                          lokal starten und im Browser öffnen
bauwerk server --port 8088 --daten ./daten
bauwerk run teil.json --out teil.step
bauwerk pruefen teil.json
```
