# Paketwerk

Paketverfolgung für alle Bestellungen – läuft als Stack auf dem Proxmox-NUC (Port 8079).

**Woher die Pakete kommen**
- **Gmail:** Versandmails (Amazon, AliExpress, Bambu Lab, DHL, Hermes, DPD, GLS, UPS …) werden alle 10 Minuten gelesen. Paketwerk ändert nichts im Postfach.
- **Von Hand:** über das Plus oben. Vom iPhone aus geht auch `http://192.168.1.30:8079/?nummer=XYZ&titel=…`, zum Beispiel aus einem Kurzbefehl.
- **Rechnungs-Modul:** neue Bestellungen aus SchichtLohn erscheinen als „bestellt“. Sobald die Versandmail kommt, wird die Sendungsnummer automatisch dazugeschrieben.

**Woher der Status kommt**
- DHL und Deutsche Post: über 17TRACK mit fester Versender-Kennung „DHL Paket“. DHL gibt die eigene Schnittstelle inzwischen nur noch an Firmen frei; ist doch ein DHL-Schlüssel eingetragen, nutzt Paketwerk ihn zuerst.
- Alle anderen Versender: über 17TRACK (kostenloser Schlüssel von api.17track.net).
- Amazon-eigene Sendungen (TBA…) und Amazon-Pakete ohne Sendungsnummer laufen nur über die Amazon-Mails („Versandt“, „Kommt heute“, „Zugestellt“) und verbrauchen kein 17TRACK-Kontingent. Liefert DHL, Hermes oder DPD für Amazon aus, wird ganz normal abgefragt.

**Meldungen** laufen über das Meldewerk: WhatsApp und Alexa lassen sich je Status getrennt ein- und ausschalten. Die Nachtruhe und die Alexa-Geräte stellst du im Meldewerk ein.

Zugestellte Pakete wandern nach 3 Tagen ins Archiv. Gelöschte Pakete werden auch aus späteren Mails nicht wieder angelegt.

**Update:** Stack neu starten – er holt sich beim Start die neueste Fassung aus diesem Ordner.
