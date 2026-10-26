# FilamentLager in Bambuddy

Das Lager aus SchichtLohn, mit Bambuddys Inventar als Datenquelle und als Eintrag in Bambuddys Seitenleiste. Bambuddy bleibt unverändert und wird weiter ganz normal aktualisiert.

## Was es macht

- **Sorten statt Spulen:** Gleiche Spulen aus Bambuddy (Marke, Material, Variante, Farbe, Nenngewicht) erscheinen als eine Sorte mit Rollen und Resten – wie im SchichtLohn-Lager.
- **Bearbeiten wirkt in Bambuddy:** „+ Rolle“ legt eine Spule an (bzw. holt eine archivierte zurück), „− Rolle“ setzt eine Spule auf leer und archiviert sie, ein geänderter Rest ändert `weight_used`. Preis, Farbe, Düsentemperatur und Filamentprofil werden in allen Spulen der Sorte gespeichert, die übrigen Lager-Angaben im Notizfeld (`SL:{…}`).
- **Abbuchen:** Bambu-Drucke bucht Bambuddy nach Druckende selbst ab (aus der 3MF bzw. dem AMS), genau einmal auf dem Server. Der Verlauf erscheint in der Lager-Statistik. Creality-Drucke aus der Creality-Cloud bucht SchichtLohn wie bisher ab, nur eben in Bambuddy.
- **AMS:** Ort im AMS, „Fächer ohne Zuordnung“ und AMS-Feuchte kommen live aus Bambuddys Druckerstatus.
- „Nicht zugeordnet“ und die Lager-Einstellungen liegen im Browser.

## Einrichten (Linux-Server, auf dem Bambuddy läuft)

```bash
git clone https://github.com/MitKIprogrammieren/Schichtlohn.git
cd Schichtlohn/bambuddy
docker compose up -d
```

Danach im Browser `http://<server>:8091/` öffnen – das ist das Lager. Die ganze SchichtLohn-App (mit Rechner, Aufträgen …) liegt unter `http://<server>:8091/index.html`.

**In Bambuddy einhängen:** Einstellungen → Externe Links → Neuer Link
- Name: `FilamentLager`
- URL: `http://<server>:8091/`
- Icon: `package`
- „In neuem Tab öffnen“: aus (dann zeigt Bambuddy das Lager direkt in seiner Oberfläche)

### Wenn in Bambuddy die Anmeldung eingeschaltet ist

In Bambuddy unter Einstellungen → API-Schlüssel einen Schlüssel mit „Status lesen“ und „Inventar verwalten“ anlegen und in `docker-compose.yml` bei `BAMBUDDY_API_KEY` eintragen, dann `docker compose up -d`. Der Schlüssel bleibt im Container.

Ohne Anmeldung in Bambuddy kann jeder im Heimnetz, der Port 8091 erreicht, das Inventar ändern – genauso wie in Bambuddy selbst.

### Andere Adresse von Bambuddy

Läuft Bambuddy nicht auf demselben Rechner bzw. nicht auf Port 8000, `BAMBUDDY_URL` anpassen (z. B. `http://192.168.178.20:8000`).

## Aktualisieren

- **Bambuddy:** wie gewohnt (`docker compose pull && docker compose up -d` im Bambuddy-Ordner).
- **Lager/SchichtLohn:** `cd Schichtlohn && git pull` – der Container liefert die neuen Dateien sofort aus, ein Neustart ist nicht nötig.

## Technik

- `docker-compose.yml`: nginx (offizielles Image), liefert dieses Repo aus und leitet `/api/` samt WebSocket an Bambuddy weiter. So laufen Lager und Bambuddy-API über dieselbe Adresse; Bambuddy erlaubt keine Aufrufe von fremden Adressen (kein CORS).
- `nginx.conf.template`: setzt beim Ausliefern `window.SL_BAMBUDDY` in `index.html` – nur dann arbeitet SchichtLohn im Bambuddy-Modus. Auf schichtlohn.pages.dev und GitHub Pages ändert sich nichts.
- `adapter.js`: Übersetzung zwischen Lager-Sorten und Bambuddy-Spulen (`/api/v1/inventory/spools`, `/inventory/usage`, `/printers/{id}/status`, WebSocket `/api/v1/ws`).
