# Änderungen

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
