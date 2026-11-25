# Paketwerk

Paketverfolgung für alle Bestellungen – läuft als Stack auf dem Proxmox-NUC (Port 8097).

**Woher die Pakete kommen**
- **Gmail:** Versandmails (Amazon, AliExpress, Bambu Lab, DHL, Hermes, DPD, GLS, UPS …) werden alle 10 Minuten gelesen. Paketwerk ändert nichts im Postfach.
- **Von Hand:** über das Plus oben. Vom iPhone aus geht auch `http://192.168.1.30:8097/?nummer=XYZ&titel=…`, zum Beispiel aus einem Kurzbefehl.
- **Rechnungs-Modul:** neue Bestellungen aus SchichtLohn erscheinen als „bestellt“. Sobald die Versandmail kommt, wird die Sendungsnummer automatisch dazugeschrieben.

**Woher der Status kommt**
- DHL und Deutsche Post: über die DHL-Schnittstelle (kostenloser Schlüssel von developer.dhl.com, bis zu 240 Abfragen am Tag).
- Alle anderen Versender: über 17TRACK (kostenloser Schlüssel von api.17track.net).
- Amazon-Pakete ohne Sendungsnummer werden über die Amazon-Mails verfolgt („Versandt“, „Kommt heute“, „Zugestellt“).

**Meldungen** laufen über das Meldewerk: WhatsApp und Alexa lassen sich je Status getrennt ein- und ausschalten. Die Nachtruhe und die Alexa-Geräte stellst du im Meldewerk ein.

Zugestellte Pakete wandern nach 3 Tagen ins Archiv. Gelöschte Pakete werden auch aus späteren Mails nicht wieder angelegt.

**Update:** Stack neu starten – er holt sich beim Start die neueste Fassung aus diesem Ordner.
