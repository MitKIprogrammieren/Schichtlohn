# Änderungen

## 3.15.6 – 08.11.2026
- Interne Prüfausgabe für die Fach-Bindung im Filament Manager. Für dich ändert sich nichts.
- Server-Änderung: Update der SchichtLohn-App in Home Assistant einspielen.

## 3.15.5 – 08.11.2026
- Filament Manager: Rollen hängen jetzt am richtigen AMS-Fach. In Bambu Studio und der Handy-App steht die Fremdrolle damit am passenden Fach des Druckers, nicht mehr nur lose in der Liste.
- Läuft über die normale Bambu-Cloud, nichts wird am Drucker umgestellt. Rollen mit Bambu-Chip macht Bambu weiter selbst.
- Server-Änderung: Update der SchichtLohn-App in Home Assistant einspielen.

## 3.15.4 – 08.11.2026
- Vorbereitung: SchichtLohn liest jetzt die Modul-Liste der Drucker aus (für den nächsten Schritt im Filament Manager). Für dich ändert sich nichts Sichtbares.
- Server-Änderung: Update der SchichtLohn-App in Home Assistant einspielen.

## 3.15.3 – 08.11.2026
- „Ins Fach am Drucker schreiben“ gibt es nur noch bei Druckern, die im Heimnetz (LAN-Modus) verbunden sind. Über die Bambu-Cloud lehnt die Drucker-Firmware solche Befehle ab und meldete am Drucker „Überprüfung des MQTT-Befehls fehlgeschlagen“ – das kommt jetzt nicht mehr vor. Stattdessen steht dort ein Hinweis.
- Server-Änderung: Update der SchichtLohn-App in Home Assistant einspielen.

## 3.15.2 – 08.11.2026
- AMS-Ansicht: Statt „? g“ steht bei Fächern ohne eingetragene Rolle jetzt ein Schätzwert aus dem Lager („≈ 420 g“) mit Füllbalken – derselbe Wert, der an Bambu Studio geht. Tippen aufs Fach zum Wiegen oder Eintragen macht ihn genau.
- Server-Änderung: Update der SchichtLohn-App in Home Assistant einspielen.

## 3.15.1 – 08.11.2026
- Filament Manager: Fächer, bei denen noch keine Rolle mit Gramm eingetragen ist, kommen jetzt auch rein – mit einem Schätzwert aus dem Lager (genau ein angebrochener Rest → dieser, sonst eine volle Rolle). In Bambu Studio steht dann „geschätzt“ in der Notiz. Genau wird es, sobald du die Rolle wiegst oder einträgst.
- Server-Änderung: Update der SchichtLohn-App in Home Assistant einspielen.

## 3.15.0 – 08.11.2026
- Füllstand auch in Bambu Studio: SchichtLohn trägt deine Rollen mit den aktuellen Gramm in den Filament Manager deines Bambu-Kontos ein. Studio und die Handy-App zeigen dann auch bei Fremdrollen, wie voll sie sind. Einschalten unter Einstellungen → SchichtLohn-Server → „Bambu Studio · Filament Manager“.
- Zur Wahl: „Rollen im AMS“ (nur was gerade im Drucker steckt) oder „Ganzes Lager“ (auch die Rollen im Regal, ohne Bambu-Lab-Sorten – die kommen über den Chip von selbst). „Aus“ entfernt die Einträge wieder.
- Nach jeder Abbuchung, jedem Wiegen und alle 30 Minuten wird nachgezogen – auch wenn Bambu einen Wert von sich aus verstellt hat. Rollen mit Bambu-Chip und eigene Einträge in Bambu Studio bleiben unberührt.
- Braucht die Anmeldung unter Bambu-Cloud. Server-Änderung: Update der SchichtLohn-App in Home Assistant einspielen.

## 3.14.1 – 08.11.2026
- Genauerer Absturz-Wächter: Lädt Safari die App neu, weil sie zu viel Speicher braucht, steht jetzt im Protokoll der SchichtLohn-App, was die App zu dem Zeitpunkt im Speicher hatte – mit einem Verlauf der letzten drei Stunden (alle 10 Minuten ein Messpunkt). Daran lässt sich erkennen, was mit der Zeit wächst.
- Die Absturzmeldung wurde bisher vom Server abgelehnt; jetzt kommt sie an.
- Server-Änderung: Update der SchichtLohn-App in Home Assistant einspielen.

## 3.14.0 – 08.11.2026
- Gewicht live: Legst du eine Rolle auf die Waage, läuft die Zahl im Lager, unter „Heute“ und bei „Spule erkannt“ flüssig mit (bis zu 10 Werte pro Sekunde) statt in Sprüngen. Auch „Filament übrig“ und der Füllbalken gehen mit.
- Die schnellen Werte werden nur angezeigt, nicht gespeichert – im Lager bleibt es bei einem Wert pro Sekunde.
- Waage 1 (Sensorplatine) kann das schon; Waage 2 (SC01 Plus) braucht dafür die Display-Firmware 1.14.0.
- Server-Änderung: Update der SchichtLohn-App in Home Assistant einspielen.

## 3.13.0 – 07.11.2026
- Leere Spule je Hersteller: unter Einstellungen → Lager steht, was die leere Spule eines Herstellers wiegt – voreingestellt Polymaker mit 140 g (Herstellerangabe für die 1-kg-Pappspule). Gilt für alle Sorten dieses Herstellers, auch neue: an der Waage, im Lager und bei „Spule erkannt“. Alle anderen bleiben bei 250 g.
- Bei jeder Sorte gibt es jetzt das Feld „Leere Spule“ (unter „Technische Daten“) für Ausnahmen, z. B. nach dem Wiegen einer leeren Spule. Ein eigener Wert geht immer vor.
- Server-Änderung: Update der SchichtLohn-App in Home Assistant einspielen.

## 3.12.1 – 07.11.2026
- Waagen bekommen einen eigenen Anzeigenamen: unter Waage → Einstellen → „Anzeigename in SchichtLohn“ – groß, klein und mit Leerzeichen, z. B. „Filamentwaage ohne Display“. Die Waage startet dafür nicht neu; der Name im Netzwerk bleibt klein. Geht auch bei Waagen ohne eigene Web-Oberfläche.
- Nur Oberfläche: in SchichtLohn → Einstellungen „Aktualisieren“ reicht.

## 3.12.0 – 07.11.2026
- NFC-Aufkleber über die Waage beschreiben: Im Fenster „Etikett“ einer Sorte „Über die Waage beschreiben“ tippen und die Rolle mit einem leeren NTAG213/215-Aufkleber auf die Waage legen. Die Waage schreibt den Link zur Rolle drauf und merkt sich den Chip bei der Sorte – danach öffnet das iPhone die Rolle, wenn man es an den Aufkleber hält, und die Waage erkennt sie.
- Braucht die neue Waagen-Firmware (Sensorplatine 2.26.0, SC01 Plus ohne Sensorplatine 1.13.0).
- Server-Änderung: Update der SchichtLohn-App in Home Assistant einspielen.

## 3.11.0 – 07.11.2026
- Waagen aktualisieren sich selbst: „Nach Update suchen“ an der Waage holt die neue Firmware über SchichtLohn von GitHub (`/api/waagen_update/…`). Die Waagen brauchen dafür kein HTTPS.
- Server-Änderung: Update der SchichtLohn-App in Home Assistant einspielen.

## 3.10.2 – 07.11.2026
- Fast leere Rolle (30 g oder weniger): „Achtung: ±10 g möglich“ auf „Spule erkannt“, auf „Heute“ und bei den Waagen im Lager – Leerspulen wiegen je nach Papphülse ein paar Gramm mehr oder weniger.
- Nur Oberfläche: in SchichtLohn → Einstellungen „Aktualisieren“ reicht.

## 3.10.1 – 07.11.2026
- Etikettendruck über SchichtLohn: Anfragen gehen jetzt direkt an Home Assistant statt über den Supervisor – die Druck-Integration hatte sie mit „nur im Heimnetz“ abgelehnt.
- Server-Änderung: Update der SchichtLohn-App in Home Assistant einspielen.

## 3.10.0 – 07.11.2026
- Etikettendruck für Waagen, die an SchichtLohn melden: Der Server reicht die Aufrufe an deine Integration m20_druckbruecke in Home Assistant weiter. Waage 2 (SC01 Plus) zeigt damit M20 Pro und M110 und kann darauf drucken, statt „Integration m20_druckbruecke fehlt“ zu melden.
- Server-Änderung: Update der SchichtLohn-App in Home Assistant einspielen.

## 3.9.9 – 07.11.2026
- Lager, Waagen: Die erkannte Rolle („Per NFC erkannt“) steht jetzt direkt unter dem Gewicht. Temperatur und Speicher stehen nur noch klein ganz unten (orange, wenn es zu warm oder voll wird).
- Nur Oberfläche: in SchichtLohn → Einstellungen „Aktualisieren“ reicht.

## 3.9.8 – 07.11.2026
- Stil „Türkis“, Lager: Zusätze wie „21 % von 1 kg“ oder „A1 mini“ stehen wieder hinter dem Wert statt darunter – die Kacheln bleiben flach. Nur wenn es nicht passt, rutscht der Zusatz in die nächste Zeile.
- Nur Oberfläche: in SchichtLohn → Einstellungen „Aktualisieren“ reicht.

## 3.9.7 – 07.11.2026
- Stil „Türkis“: Im Lager sehen AMS-Feuchte und die Waagen jetzt aus wie „Bestand“ – jeder Wert als Kachel mit farbigem Streifen, auf dem Handy zwei nebeneinander.
- Nur Oberfläche: in SchichtLohn → Einstellungen „Aktualisieren“ reicht, kein Update in Home Assistant nötig.

## 3.9.6 – 07.11.2026
- „Heute“ mit zwei Waagen: auf dem iPhone ein gemeinsamer Block „Waagen“ mit „Waage 1“ und „Waage 2“, auf Mac und iPad stehen die beiden Waagen nebeneinander.
- Nur Oberfläche: in SchichtLohn → Einstellungen „Aktualisieren“ reicht, kein Update in Home Assistant nötig.

## 3.9.5 – 07.11.2026
- „Heute“: Jede Waage hat ihren eigenen Block („Waage 1“, „Waage 2“) – liegen auf beiden Rollen, siehst du beide.
- „Heute“ auf dem Handy: Der Text unter der Rolle („etwa … g Filament · … %“) bricht jetzt um, statt unter die Grammzahl zu laufen.
- Nur Oberfläche: in SchichtLohn → Einstellungen „Aktualisieren“ reicht, kein Update in Home Assistant nötig.

## 3.9.4 – 07.11.2026
- „Spule erkannt“: Jede Waage hat ihr eigenes Feld – liegen auf beiden Waagen Rollen, stehen zwei Felder nebeneinander (auf dem Handy untereinander). Jedes Feld lässt sich einzeln schließen. Rollen, die beim Öffnen schon aufliegen, werden auch gezeigt (ohne Ton).

## 3.9.3 – 07.11.2026
- Lager auf dem Handy: Nichts läuft mehr über den rechten Rand hinaus. Der Bestand zeigt Gesamt, Sorten, Rollen und Wert als vier gleich große Kacheln in zwei Reihen, die Werte der Waagen stehen ordentlich in zwei Spalten.

## 3.9.3 – 07.11.2026
- „Heute“: Die Waagen-Karte nennt jetzt die Waage, die gerade etwas zeigt („Waage 1“ oder „Waage 2“), statt nur „Waage“.

## 3.9.2 – 07.11.2026
- „Spule erkannt“: Hältst du eine Rolle mit NFC-Chip an eine Waage, erscheint auf „Heute“ und im Lager oben eine Karte mit Material, Farbe, Restgewicht und Tag-ID – mit kurzem Ton. Bekannte Rollen öffnest du mit „Zur Rolle“, neue Bambu-Spulen legst du mit „Neu anlegen“ gleich mit allen Werten an. Auf dem iPhone kommt der Ton, sobald du die App einmal angetippt hast.
- Zwei Waagen heißen jetzt „Waage 1“ und „Waage 2“ (statt „Filamentwaage-2“).

## 3.9.1 – 06.11.2026
- Neuer Stil „Türkis“ unter Einstellungen → Design: dunkel mit türkisem Akzent, Kennzahlen als Kacheln mit farbigem Streifen, Reiter als umrandete Pillen und kräftigere Füllbalken im Lager. Die Rollen sehen aus wie bisher. Hell und dunkel möglich.

## 3.9.0 – 06.11.2026
- Waage erkennt Rollen per NFC: Auf „Heute“ und in der Waage-Kachel im Lager steht jetzt, welche Rolle gerade aufliegt – mit Farbe, Herstellerlogo und Material. Bambu-Chips werden auch erkannt, wenn die Sorte noch nicht im Lager ist.
- Die Waage zeigt jetzt auch, wie viel Filament noch auf der Rolle ist (ohne Leerspule, mit Anteil an der vollen Rolle).
- „Heute“ und Einkaufsliste: Rollen sehen aus wie im Lager (in Farbe, mit Füllstand) und tragen das Herstellerlogo. Neue Symbole im SchichtLohn-Look für Trocknen, Feuchte und Warnungen.

## 3.8.9 – 06.11.2026
- Das Gewicht der Waage erscheint im Lager schneller (zusammen mit Waagen-Firmware 2.24.6 nach etwa 1–2 Sekunden).

## 3.8.8 – 06.11.2026
- „Waage einstellen“: Das Fenster lässt sich wieder mit dem X schließen und lädt nicht mehr bei jedem Klick neu (Eingaben blieben dadurch nicht stehen).

## 3.8.7 – 05.11.2026
- Waage aus SchichtLohn einstellen: In der Kachel jeder Waage gibt es jetzt „Einstellen“ – Tara, Kalibrieren, Nullpunkt-Nachführung, Leerspulen-Gewichte, NFC, Etiketten und Name. Klappt auch unterwegs und in der Home-Assistant-App, weil SchichtLohn die Einstellungen an die Waage weiterreicht.
- Daneben öffnet ein Link-Knopf die komplette Weboberfläche der Waage (im Heimnetz oder über Tailscale).

## 3.8.6 – 05.11.2026
- Gleiche Sorte in verschiedenen Rollengrößen (z. B. 1 kg und 2 kg): Rollen, die nicht 1 kg haben, tragen die Größe jetzt im Namen („… · 2 kg“).
- Abbuchen nach Fach: Passen mehrere Sorten zu einem AMS-Fach, bucht SchichtLohn bei der Sorte ab, deren Rolle in diesem Fach eingetragen ist. Im Fenster des Fachs wählst du dafür unter „Welche Rolle steckt drin?“ die richtige Sorte. „Ins Fach am Drucker schreiben“ merkt sich die Sorte ebenfalls für das Abbuchen.

## 3.8.5 – 05.11.2026
- Mehrere Waagen: Bekommt eine weitere Filamentwaage in ihren Einstellungen einen eigenen Namen (z. B. „waage2“), zeigt SchichtLohn sie als eigene Kachel im Lager. Beim Wiegen einer Rolle nimmt SchichtLohn das Gewicht der Waage, auf der zuletzt etwas gelegt wurde.

## 3.8.4 – 04.11.2026
- Telegram-Meldungen einstellbar: bei welchen Prozenten der Fortschritt gemeldet wird (z. B. 50 %, 25/50/75 %, alle 10 % oder eigene Stufen), eine Meldung kurz vor Druckende (5–30 Minuten vorher), welche Ereignisse überhaupt gemeldet werden (Start, Pause, fertig, abgebrochen, Fehler) und ob das Kamerabild mitkommt. Zu finden unter Einstellungen → Meldungen → Telegram.

## 3.8.3 – 04.11.2026
- Neu: Dateimanager. Unter Druckaufträge zeigt „Dateien“ alle Druckdateien, die SchichtLohn von den Druckern gesichert hat – mit Bild, Drucker, Datum, Druckzeit, Gramm und Farben. Suchen, nach Drucker filtern, sortieren, herunterladen oder löschen.
- Neu: Druckdateien wieder an einen Drucker schicken – nur hochladen oder direkt starten. Vor dem Start wählst du Platte und AMS-Fächer; SchichtLohn schlägt die passenden Fächer vor und lässt nur Drucker zu, für die die Datei geslict ist.
- Neu: Ein AMS-Fach antippen und unter „Im Drucker eintragen“ eine Sorte aus dem Lager wählen – der Drucker übernimmt Material, Farbe, Profil und Düsentemperatur wie bei „Fach bearbeiten“ in Bambu Studio.
- Neu: Notaus je Drucker (roter Knopf in „Drucker jetzt“): Druck stoppen (2× tippen) oder Strom aus über die zugeordnete Steckdose in Home Assistant (3× tippen).
- Eingeklappte AMS bleiben eingeklappt.

## 3.8.2 – 04.11.2026
- Abgebrochene Drucke zeigen jetzt neben der abgebuchten Menge auch, wie viel die ganze Druckdatei gebraucht hätte – z. B. „34 von 46 g“ auf der Kachel und unter „Zuletzt abgebucht“. Gilt auch, wenn Teile übersprungen wurden. Abgebucht wird weiter nur, was wirklich gedruckt wurde.

## 3.8.1 – 03.11.2026
- Neu: Installer für Synology und andere Server mit Docker. Ein Befehl richtet SchichtLohn ein, fragt nach Tailscale, Preisquellen (Shops, eBay, AliExpress – jede einzeln wählbar) und Zugangsschlüssel und kann die Daten vom bisherigen Server übernehmen.
- Beim Übernehmen kannst du wählen: alles inklusive Zugänge oder nur Lager, Drucke und Preise – dann bleiben eBay-, AliExpress- und Claude-Schlüssel beim alten Server.

## 3.8.0 – 03.11.2026
- Neu: Jede Rolle im AMS hat ihre eigene Grammzahl. Unter jeder Spule in „Drucker jetzt“ steht, wie viel auf genau dieser Rolle ist – auch wenn mehrere Rollen derselben Sorte im AMS stecken.
- Ein Tipp aufs Fach öffnet die Rolle: Gramm von der Waage übernehmen (Leerspule wird abgezogen), „Volle Rolle“ oder Gramm von Hand eintragen. Dort steht auch, was seit dem Eintragen von dieser Rolle abgebucht wurde, mit Druckdatei und Zeit.
- Nach dem Druck zieht SchichtLohn genau von der Rolle im benutzten Fach ab. Läuft sie leer und das AMS wechselt auf dieselbe Sorte in einem anderen Fach, wird der Rest dort abgebucht.
- Verbrauch: Unten stehen jetzt die einzelnen Drucke mit Dateiname, Zeit, Drucker, Fach und Sorte – abgebrochene und von Hand zugeordnete sind markiert.

## 3.7.1 – 03.11.2026
- Neu in den Einstellungen unter „SchichtLohn-Server“: die Karte „Zugang“. Dort erzeugst du einen Schlüssel für den Server, trägst einen eigenen ein oder schaltest ihn wieder aus – ohne Umweg über Home Assistant. Der Schlüssel bleibt bei Updates erhalten und wird nur auf Knopfdruck neu erzeugt.
- Neu: die Karte „Claude“ mit der Adresse zum Kopieren, mit der Claude direkt mit deinem Lager arbeitet.
- Beim Umzug von einem anderen Server behält der neue Server seinen eigenen Schlüssel.

## 3.7.0 – 03.11.2026
- Neu: Claude kann direkt mit SchichtLohn arbeiten. Über eine eigene Adresse fragt Claude dein Lager, die Drucker, das Druckprotokoll und den Verbrauch ab, legt Sorten an, ändert Druckwerte, Preise oder Bestand und bucht Verbrauch ab. Löschen geht nur in der App.
- Die Adresse enthält einen geheimen Schlüssel. Wer sie kennt, kann das Lager ändern – also nicht weitergeben.

## 3.6.2 – 02.11.2026
- Kamera: Das Live-Bild lädt jetzt zuverlässig. Bisher blieb es bei manchen Druckern (z. B. H2C) schwarz.
- Das Kamerabild ist am großen Bildschirm nicht mehr so riesig, auch im Vollbild passt es ins Fenster.

## 3.6.1 – 02.11.2026
- Neu: „Zuletzt abgebucht“ unter Druckaufträge. Dort siehst du nach jedem Druck, was von welcher Spule abgezogen wurde und wie viel noch da ist. Nicht zugeordnete Reste kannst du direkt zuordnen.
- Nach einer Abbuchung kommt in der App eine deutliche Meldung mit Spule, Gramm und Restbestand. Öffnest du die App später, siehst du, wie viele Abbuchungen seitdem dazugekommen sind.

## 3.6.0 – 02.11.2026
- Neu: Druckerkameras in „Druckaufträge“ → „Drucker jetzt“. Das Kamerasymbol neben einem Drucker öffnet das Live-Bild, ein Tipp aufs Bild zeigt es im Vollbild. Die Bilder kommen über Home Assistant, damit gehen sie auch unterwegs über Tailscale.
- Unten im Block stellst du ein, wie oft das Bild kommt: Live, jede Sekunde, alle 2 oder alle 5 Sekunden. Klappt der Live-Strom nicht, kommt automatisch jede Sekunde ein neues Bild.

## 3.5.0 – 02.11.2026
- Neu: Reiter „Preisvergleich“. Such nach Marke, Material oder Farbe (z. B. „PETG schwarz“) und sieh alle Shops nebeneinander – nach Preis je kg sortiert, die günstigste Spule markiert, Sorten aus deinem Lager gekennzeichnet.
- eBay und AliExpress werden dabei live mitgesucht (mit Versand, wenn der Händler ihn nennt, sonst mit deiner Pauschale).
- Startseite mit den günstigsten 1-kg-Spulen je Material und Marke. Filter für Material, Gewicht, Spule/Refill und Marke.

## 3.4.0 – 02.11.2026
- Neu: Der Server liest jetzt alle Druckdateien aus dem Speicher deiner Drucker (auch aus Unterordnern) und legt von jeder eine Kopie auf dem Server ab. Zeitraffer und Protokolldateien bleiben auf dem Drucker.
- Neu: Drucke ohne Gramm (z. B. aus Spooly) werden mit der passenden Druckdatei ergänzt – Gramm je Filament und Druckzeit laut Datei, bei abgebrochenen Drucken anteilig. Drucke ohne Bild bekommen das Vorschaubild aus der Datei.

## 3.3.3 – 02.11.2026
- Behoben: Die App (vor allem auf dem iPhone über Tailscale) zeichnete sich ständig komplett neu, wenn die Verbindung zum Server kurz abriss. Der Server meldet sich jetzt öfter, damit die Verbindung offen bleibt, und die App zeichnet nur noch neu, wenn sich wirklich etwas geändert hat.

## 3.3.2 – 02.11.2026
- Neu: „Spooly-Import entfernen“ unter Einstellungen → SchichtLohn-Server → Druckprotokoll nimmt alle aus Spooly übernommenen Drucke wieder heraus.
- Der Spooly-Import nimmt nur noch die Druckliste aus Spooly an und meldet bei einer falschen Datei, was darin war.

## 3.3.1 – 01.11.2026
- Behoben: Nach einem Neustart des Servers konnte die Druckerliste verschwinden, wenn mehrere Drucker gleichzeitig über die Cloud verbunden wurden – dabei gingen auch die IP-Adressen verloren.
- Behoben: Beim Übernehmen aus der Bambu-Cloud oder beim Bearbeiten eines Druckers konnte ein veralteter Stand die eingetragenen Drucker überschreiben – dabei gingen IP-Adressen verloren. Jetzt wird die Druckerliste vorher immer frisch geholt, IP und Zugangscode bleiben erhalten, und die Liste kann nicht mehr versehentlich ganz geleert werden.

## 3.3.0 – 01.11.2026
- Neu: Der Server schreibt jeden Druck mit, den er enden sieht – auch Drucke, die Bambu Studio direkt übers Heimnetz schickt und die deshalb nicht in der Bambu-Cloud stehen. Mit Name, Zeit, Gramm je Filament und Vorschaubild aus der Druckdatei. Du findest sie unter „Druckaufträge“.
- Neu: Alle 6 Stunden liest der Server die Druckdateien im Speicher deiner Drucker (bei Druckern mit IP-Adresse). So tauchen auch ältere Drucke auf, mit Gramm und Druckzeit laut Datei.
- Neu: Drucke aus Spooly übernehmen – unter Einstellungen → SchichtLohn-Server → Druckprotokoll die Datei aus Spooly auswählen.

## 3.2.48 – 01.11.2026
- Fächer und Sorten werden jetzt nach der Farbe zugeordnet, wie das Auge sie sieht: Grau bleibt Grau, egal ob hell oder dunkel, und wird nicht mehr mit einem hellen Grün verwechselt. Gilt für die Anzeige im Lager, die Meldung „Fach nicht zugeordnet“ und die Abbuchung nach dem Druck.

## 3.2.47 – 01.11.2026
- Fächer werden wieder erkannt: Beim ersten Start holt sich der Server einmal die Bambu-Profile und gelernten AMS-Farben, die du früher in Home Assistant den Sorten zugeordnet hast. Nur fehlende Angaben werden ergänzt – Bestand, Preise und alles andere bleiben, wie sie sind.

## 3.2.46 – 01.11.2026
- Neu: „Fach nicht zugeordnet“ kommt jetzt vom SchichtLohn-Server und prüft gegen dein SchichtLohn-Lager. Legst du ein Filament ins AMS (oder änderst Profil oder Farbe) und keine Sorte mit Bestand passt, bekommst du eine Handymeldung mit bis zu drei Vorschlägen.
- Ein Vorschlag in der Meldung öffnet SchichtLohn und ordnet das Fach gleich zu – „In SchichtLohn öffnen“ zeigt die Auswahl aller Sorten.
- Ist das Fach danach zugeordnet, verschwindet die Meldung vom Handy von selbst.

## 3.2.45 – 01.11.2026
- Lager: Die Auswahlmenüs (Material, Marke, Farbe, Ort, Sortierung) klappen nicht mehr von selbst zu, wenn Waage oder Drucker neue Werte melden – vor allem in Home Assistant hingen sie dadurch.

## 3.2.44 – 01.11.2026
- Einstellungen bleiben auf allen Geräten gleich: Speichert ein Gerät, das länger offen war (z. B. die Home-Assistant-App auf dem Mac), überschreibt es nicht mehr, was du inzwischen auf dem Handy eingestellt hast – es werden nur die Werte übernommen, die du auf diesem Gerät geändert hast.
- Kommt SchichtLohn aus dem Hintergrund zurück oder war kurz die Verbindung weg, holt es sich zuerst den aktuellen Stand von Einstellungen, Portfolio und Aufträgen.

## 3.2.43 – 01.11.2026
- Preise aus Shopseiten: Auch Sammelseiten (z. B. colorfabb.com „3D-Druck-Filamente“) werden jetzt deinen Sorten zugeordnet – Material und Farbe kommen aus dem Variantennamen („Varioshore TPU 95A Schwarz“).
- Preisliste: colorFabb Varioshore TPU von 3DJake ist dabei.
- Rechnungen: Leerzeichen in der Suche gehen wieder; alte Bambu-Rechnungen ohne Farbcode übertragen ihre Preise jetzt auch ins Lager.

## 3.2.42 – 01.11.2026
- Lagerpreise aus Amazon-Rechnungen: Bei Sorten mit Rechnungspreis steht jetzt „Gekauft bei Amazon · Händler · Datum“ mit Link zum Artikel – im Bearbeiten-Fenster unter „Preis je kg“ und in der Preisliste beim Lagerpreis. Auch Preise aus Bambu-Rechnungen zeigen, woher sie kommen.
- Änderst du den Preis von Hand, verschwindet der Hinweis automatisch.

## 3.2.41 – 01.11.2026
- Spulentypen heißen jetzt: Klar, Bambu Spule, FD3D, JAYO, Sunlu/JAYO, TINMORRY, FILAXIX und Polymaker.

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
