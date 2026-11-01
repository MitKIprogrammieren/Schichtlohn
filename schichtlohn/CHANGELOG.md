# Änderungen

## 3.2.40 – 01.11.2026
- Lager: Neuer Spulentyp „Schwarz mit Schlitzen“ – vier schmale Fenster mit je drei Kammern, an denen man den Füllstand sieht. Auswählbar unter Einstellungen → „Spule je Marke“.

## 3.2.39 – 01.11.2026
- Lager: Neuer Spulentyp „Klarsicht mit Rippen“ – durchsichtiger Flansch mit Rippengitter, glatter Fläche und großer klarer Nabe. Auswählbar unter Einstellungen → „Spule je Marke“.

## 3.2.38 – 01.11.2026
- Einstellungen: Neben jeder Marke zeigt ein kleines Bild, wie ihre Spule aussieht – es ändert sich sofort beim Umstellen.
- Kürzere Namen: „Milchig“ und „Lochmuster“.
- Auf dem Handy steht für die Einstellungen jetzt ein Zahnrad-Symbol in der Reiterleiste statt „Mehr“.

## 3.2.37 – 01.11.2026
- Lager: Neue Spulentypen – halbdurchsichtig (milchig), schwarz mit Lochmuster, Pappe schwarz-weiß und schlichte Pappe, dazu weiter Klarsicht und dunkel mit Fenstern.
- Unter Einstellungen → „Spule je Marke“ bekommt jede Marke aus dem Lager ihre eigene Spule; neue Marken bekommen den eingestellten Standard.
- Neu: „Spulen drehen sich“ – nur beim Drucken, immer langsam oder nie.
- Alles in allen drei Ansichten (stehend, frontal, flach liegend) und in der PDF-Bestandsliste.

## 3.2.36 – 01.11.2026
- Rechnungen: Bilder für Bambu-Lab-Bestellungen kommen jetzt aus dem Bambu-Store – bei Filament in der gekauften Farbe. Die Produktbilder sind außerdem größer und schärfer.

## 3.2.35 – 01.11.2026
- Rechnungen: Zu jeder Position gibt es jetzt ein kleines Produktbild. Der Server sucht es selbst – Amazon und AliExpress über die Artikelnummer, Bambu Lab im Bambu-Store (bei Filament in der gekauften Farbe) – und hebt es auf, damit die Karte schnell bleibt.
- Kein Bild gefunden oder ein falsches? Bild antippen und die Bildadresse aus dem Shop einfügen.

## 3.2.34 – 01.11.2026
- Lager: Die Spulen gibt es jetzt in drei Ansichten – stehend, frontal oder flach liegend. Auswahl unter Einstellungen → „Ansicht der Spulen“.
- Die Größe richtet sich nach dem Spulengewicht: 250- und 500-g-Rollen sind kleiner, 2, 3, 5 und 10 kg werden breiter und etwas größer.

## 3.2.33 – 01.11.2026
- PDF-Bestandsliste: Die neuen Spulen gibt es jetzt auch im PDF – mit Füllstand, Refill auf Kartonkern und der in den Einstellungen gewählten Spulenart. Mit „Filamentrolle (klassisch)“ bleibt das PDF wie bisher.

## 3.2.32 – 01.11.2026
- Lager: Neue Spulen. Die Wicklung zeigt, wie viel Filament auf der angebrochenen Rolle noch drauf ist – eine fast leere Rolle sieht man sofort.
- Bambu-Spulen mit Klarsicht-Flansch, andere Hersteller dunkel mit Fenstern, Refills als Wicklung auf Kartonkern. Unter Einstellungen → „Farbe der Sorten anzeigen als“ lässt sich das ändern (auch Pappspule); die alte Rolle und das Farbquadrat gibt es weiter.
- Die Rolle, mit der gerade gedruckt wird, dreht sich und der Faden läuft heraus.

## 3.2.31 – 01.11.2026
- Lagerwert springt nicht mehr: Für Rollen ohne eigenen Preis schreibt SchichtLohn den geschätzten Shop-Preis einmal am Tag fest. Vorher hing der Wert davon ab, welche Preise beim Öffnen schon geladen waren (eBay und AliExpress fehlten in der Lager-Ansicht oft).
- Der Schätzpreis ist jetzt der Median der Shop-Angebote statt des Durchschnitts – eine einzelne teure oder spottbillige Rolle verzieht ihn nicht mehr. Fällt ein Shop aus, bleibt der letzte Preis stehen.
- Eigene Lagerpreise haben weiter immer Vorrang.
- Home-Assistant-Karte: Reste eines alten Zusammenführens entfernt, die die Karte unbrauchbar machen konnten.

## 3.2.30 – 01.11.2026
- Preisliste: Selbst übernommene Shoppreise (z. B. 3dk.berlin, Bambu Lab Store) verschwinden nicht mehr, wenn der Server kurz weg war (etwa beim Update). SchichtLohn holt sie automatisch nach, sobald der Server wieder da ist.

## 3.2.29 – 01.11.2026
- Kopfzeile: Unter „SchichtLohn“ steht wieder ein Untertitel – „Lager · Preise · Drucke“.
- Bambu Lab und Creality oben eckig wie die Reiter.

## 3.2.28 – 01.11.2026
- Kopfzeile: „SchichtLohn“ größer, der Untertitel „Druckpreise kalkulieren“ ist weg.
- Der Server-Zustand steckt jetzt im Logo: grüner Punkt = erreichbar, gelb = speichert, rot = offline. Die eigene „Server“-Anzeige entfällt.
- Bambu Lab und Creality oben als ruhige Felder ohne Rahmen; auf dem Handy steht alles in einer Zeile.

## 3.2.27 – 01.11.2026
- Rechner: Die Schätzung aus ungeslicten 3MF-Dateien und STL ist deutlich genauer. Feine Oberflächen (z. B. Zapfen, Rinde, Muster) zählen nicht mehr als riesige Wandfläche, und bei 3MF werden Füllung und Wandlinien aus der Datei übernommen.

## 3.2.26 – 01.11.2026
- Rechner: Ungeslicte 3MF-Dateien werden jetzt in der richtigen Größe geschätzt. Wurde ein Modell in Bambu Studio vergrößert oder gedreht, rechnet SchichtLohn das mit ein – vorher kamen solche Teile viel zu leicht und zu schnell heraus.

## 3.2.25 – 31.10.2026
- Bestandsliste: „Nach Marke“ und die Suche gehen wieder über die ganze Breite, sind aber nur so hoch wie die Umschalter darüber.

## 3.2.24 – 31.10.2026
- Bestandsliste: Die Umschalter haben wieder ihre gewohnte Größe; nur „Nach Marke“ und die Suche sind kleiner und schmaler.

## 3.2.23 – 31.10.2026
- Bestandsliste: Umschalter, Auswahl, Suche und Spalten-Knöpfe oben sind deutlich kleiner – mehr Platz für die Liste.

## 3.2.22 – 31.10.2026
- Handy-Ansicht aufgeräumt: Die Kopfzeile bleibt beim Scrollen deckend, auch mit dem Design „Durchsichtig“ – die Liste scheint nicht mehr durch.
- Lager: Einkaufsliste, Preisliste, Bestandsliste und Rückblick als gleich breite Knöpfe; Sortierung, Filter und Auf-/Zuklappen in einer Zeile, Scannen bis Filament in einer Reihe.
- Bestandsliste: Auswahl und Suche kleiner und nebeneinander, die Vorschau ist im dunklen Design dunkel (gedruckt und als PDF bleibt sie weiß).

## 3.2.21 – 31.10.2026
- Cloud und Heimnetz gleichzeitig: Bei Druckern über die Bambu-Cloud kannst du zusätzlich die IP-Adresse eintragen. Der Drucker bleibt über die Cloud verbunden, der Server holt aber die Druckdatei übers Heimnetz – so werden übersprungene Teile und Abbrüche auch bei Cloud-Druckern genau abgebucht.
- „IP suchen“ findet den Drucker im Heimnetz von selbst (der Zugangscode kommt aus der Bambu-Cloud), „Verbindung prüfen“ zeigt, ob der Zugriff klappt.

## 3.2.20 – 31.10.2026
- Übersprungene Teile werden nicht mehr mit abgebucht: Lässt du am Drucker Teile weg, zieht SchichtLohn nur ab, was wirklich gedruckt wurde – ausgerechnet aus der Druckdatei, Schicht für Schicht. Das klappt bei Druckern im Heimnetz; über die Bambu-Cloud gibt es nur eine Schätzung oder einen Hinweis.
- Neu in Druckaufträge: „Verbrauch anpassen“. Einen Druck auswählen, echte Gramm eintragen (oder „Alles auf … %“), SchichtLohn bucht den Unterschied im Lager nach oder zurück.
- Ein Tipp auf das Vorschaubild zeigt es groß, mit Name, Drucker, Zeit und Gewicht.

## 3.2.19 – 31.10.2026
- Versand wird mitgerechnet: Nennt eBay den Versand nach Deutschland, steckt er im Preis („inkl. 4,90 € Versand“ oder „versandkostenfrei“). Fehlt die Angabe – bei AliExpress immer –, rechnet SchichtLohn deine Versandpauschale dazu.
- Die Pauschalen trägst du unter Einstellungen → Preisvergleich ein (eBay und AliExpress getrennt). Ohne Pauschale steht „zzgl. Versand“ dabei.

## 3.2.18 – 31.10.2026
- Neu: Abruf-Protokoll unter Einstellungen → Preisvergleich. Für jeden Preisabruf siehst du Zeit, Anlass (automatisch, von Hand, nach dem Speichern der Schlüssel), Dauer, Anzahl der Preise und Fehler.
- Ein Tipp auf einen Abruf zeigt für jede Sorte, was eBay und AliExpress geliefert haben: Preis, €/kg, ob per EAN oder Suche gefunden – oder warum nichts gefunden wurde.

## 3.2.17 – 31.10.2026
- eBay- und AliExpress-Preise stehen jetzt überall: als eigene Zeilen in der Preisliste (mit €/kg, günstigstes Angebot markiert), in der Einkaufsliste und bei der Filamentwahl im Rechner („AliExpress ab …“).
- Der Preis je kg stimmt auch bei Mehrfachpacks und 3-kg-Rollen: SchichtLohn liest Rollengewicht und Stückzahl aus dem Angebot.

## 3.2.16 – 30.10.2026
- Druckmeldungen über Telegram klappen jetzt auch ohne Anmeldung bei der Bambu-Cloud: SchichtLohn liest Start, Stand, Pause, Fehler und Ende dann aus Home Assistant.
- „Fertig ca.“ zeigt die richtige Uhrzeit, und die Telegram-Testmeldung kommt mit einem Bild aus der Druckerkamera.

## 3.2.15 – 30.10.2026
- Telegram meldet jetzt den ganzen Druck: Start mit Vorschaubild und Fertig-Uhrzeit, Stand bei 25, 50 und 75 % mit Foto aus der Druckerkamera, Pause und Druckerfehler.
- Die Meldung zum Druckende kommt mit einem Kamerafoto vom fertigen Druck.

## 3.2.14 – 30.10.2026
- Telegram: Leerzeichen oder Zeilenumbrüche im kopierten Token stören nicht mehr; der Token taucht nie in Fehlermeldungen auf.

## 3.2.13 – 30.10.2026
- Neu: Handy-Meldungen über Telegram – auch ohne Home Assistant. Bot bei @BotFather anlegen, Token unter Einstellungen → Server → Telegram eintragen, fertig.

## 3.2.12 – 30.10.2026
- Etiketten für den M20 Pro werden direkt in seiner Auflösung (300 dpi) gezeichnet statt hochgerechnet – Schrift und QR-Code deutlich schärfer.
- Lager startet nach Marke sortiert, Etiketten-Werte als ruhige Tabelle.

## 3.2.11 – 30.10.2026
- Standardwerte für Carbon- und Glasfaser-Filamente (z. B. ASA CF, PETG GF) kommen jetzt von den passenden CF-/GF-Profilen.

## 3.2.10 – 30.10.2026
- Druckwerte ergänzt: Fehlen bei einer Spule Düse, Bett, Flow, K-Wert oder max. Volumenstrom, kommen sie jetzt aus den Filamentprofilen von OrcaSlicer und Bambu Studio (passend zu Marke, Material, Matt/Seide/CF …). Eigene Werte bleiben unverändert.
- Gibt es kein Profil der Marke, steht der übliche Wert des Materials drin und ist als Standardwert gekennzeichnet. Der K-Wert wird nie geschätzt.

## 3.2.9 – 30.10.2026
- Zwei Etikettendrucker: Hat die Waage mehrere Phomemo-Drucker in Home Assistant (z. B. M20 Pro und M110), wählst du im Etikett-Fenster, auf welchem gedruckt wird. Die Wahl wird gemerkt.

## 3.2.8 – 30.10.2026
- Neue Herstellerlogos: Filaxix und iFilament – damit haben alle Marken im Lager ein Logo.

## 3.2.7 – 30.10.2026
- Neue Herstellerlogos: Sunlu, Eryone, QIDI und Nobufil.

## 3.2.6 – 29.10.2026
- Preisliste aufgeräumt: Shops stehen als Zeilen in der Sorten-Kachel (Name, Preis, €/kg), die günstigste ist grün hinterlegt und markiert.
- Kennzahlen als schmale Leiste statt großer Kacheln.

## 3.2.5 – 29.10.2026
- Preisliste neu gestaltet: Kennzahlen oben (Sorten, mit Preis, Shops, Ersparnis gegenüber 3DJake), Markenlogos statt Namen, kompakte Shop-Kästchen, günstigstes Angebot grün markiert.
- 3DJake wird jetzt täglich aufgefrischt (Preise, Normalpreise, EAN) und findet neue Farben bekannter Serien selbst.

## 3.2.4 – 29.10.2026
- Neue Herstellerlogos: Jayo, Polymaker, Princore, Material4Print, Spectrum, Siraya Tech, Geeetech – freigestellt, passen sich hell und dunkel an.

## 3.2.3 – 29.10.2026
- Neu: **Preisliste** im Lager. Für jede Sorte die Preise aus den Herstellershops (Tinmorry, Princore mit Fiberlogy/Polymaker/Extrudr, Sunlu EU-Lager, Polymaker, Material4Print, CR3D, Das Filament, Nobufil) und von 3DJake, mit €/kg.
- Die Shoppreise werden jeden Morgen automatisch geholt.
- Einkaufsliste zeigt die günstigsten Shops mit Link.
- Unter Einstellungen → Funktionen abschaltbar.

## 3.2.2 – 29.10.2026
- Fertige Stile, jeweils hell und dunkel: Bambu Lab, SolidCraft, Graphit, Nord, Ozean, Sand, Kontrast.
- Text auf farbigen Knöpfen passt sich der Akzentfarbe an (dunkel auf hellen Farben).

## 3.2.1 – 29.10.2026
- Neu: **Design frei einstellbar** (Einstellungen → Design): Vorlagen (Glas, Flach & eckig, Weich & rund, Schwebend, Durchsichtig), hell/dunkel/automatisch, Akzentfarbe, Ecken, Rahmen, Schatten, durchsichtige Kacheln, Seitenhintergrund, Abstände.
- Schrift passt sich bei eigener Hintergrundfarbe automatisch an.

## 3.2.0 – 29.10.2026
- Neu: **Preisvergleich mit eBay und AliExpress**. Zugangsdaten unter Einstellungen → Preisvergleich; der Server sucht täglich das günstigste Angebot je Sorte (eBay per EAN), Anzeige in der Einkaufsliste.
- Verständliche Meldung, wenn die Filamentwaage für den Etikettendruck nicht erreichbar ist.

## 3.1.9 – 29.10.2026
- Neu: **Reicht die Rolle?** – der Rechner zeigt, ob das Filament im Lager reicht, was übrig bleibt und welche Rolle als Ersatz passt.
- Neu: **Spulen-Etiketten** wie auf der Filamentwaage, mit QR-Code zur Rolle; Druck über die Waage oder als Bild teilen. Scanner und Link `?rolle=` öffnen die Rolle direkt.
- Neu: **Jahresrückblick** – Kilo, Kosten, Drucke, Lieblingsfarben, Fehldrucke eines Jahres.
- Neu: **Meldung „Druck fertig“** aufs Handy mit Vorschaubild, Dauer und Verbrauch.
- Alles einzeln abschaltbar unter Einstellungen → Funktionen.

## 3.1.8 – 29.10.2026
- Herstellerlogos auch ohne Home Assistant (z. B. über Tailscale), keine Favicons mehr.

## 3.1.7 – 29.10.2026
- Alles aktualisiert sich selbst – keine Aktualisieren-Knöpfe mehr.
- Größere Vorschaubilder bei den Druckaufträgen.

## 3.1.6 – 29.10.2026
- Einkaufsliste mit knappen und aufgebrauchten Sorten und Händler-Links, Monatsverbrauch in der Bestandskarte, Verbrauch pro Farbe.
- Meldung bei knapper Sorte, Trocknungs-Hinweis für feuchteempfindliches Filament im AMS.

## 3.1.5 – 28.10.2026
- Bambu-Anmeldung vom Server übernehmen: einmal anmelden, alle Geräte verbunden.

## 3.1.4 – 28.10.2026
- Einstellungen in Gruppen, Test-Meldung an die Handys.

## 3.1.3 – 28.10.2026
- Meldungen an alle ausgewählten Handys aus Home Assistant.
