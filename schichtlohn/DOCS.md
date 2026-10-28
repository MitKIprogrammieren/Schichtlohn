# SchichtLohn-Server

Filamentlager, Etikett- und Fotoerkennung, Bambu-Drucker mit automatischer Abbuchung und die Schnittstelle für die Waage – alles in einer App auf deinem Home Assistant.

## Öffnen

- **Seitenleiste:** „SchichtLohn“ – funktioniert auch unterwegs über Nabu Casa und in der Home-Assistant-App auf dem iPhone.
- **Im Heimnetz:** `http://<IP des Home-Assistant-Servers>:8093/app/`

## Umzug von der Synology

SchichtLohn öffnen → Einstellungen → SchichtLohn-Server → **Umzug von einem anderen SchichtLohn-Server** → Adresse der Synology (z. B. `http://192.168.1.4:8093`) → **Daten holen**. Danach den Container auf der Synology stoppen, sonst bucht er weiter ab.

## Drucker

Einstellungen → SchichtLohn-Server → Bambu-Drucker → **Aus Bambu-Cloud übernehmen** (vorher in SchichtLohn bei der Bambu-Cloud anmelden) oder von Hand mit IP und Zugangscode. Nach jedem Druck wird das Filament abgebucht. Die Meldung aufs Handy geht über Home Assistant – dafür nur den notify-Dienst eintragen (z. B. `notify.mobile_app_iphone_17_pro_max`), ein Token ist nicht nötig.

Danach in Home Assistant die Automation „FilamentLager – Abbuchung nach Druckende“ ausschalten.

## Waage

In der Waage als Home-Assistant-Adresse `http://<IP des Home-Assistant-Servers>:8093` eintragen, als Token irgendetwas, Liste `todo.filament`.

## Daten

Alles liegt im App-Ordner und ist in den Home-Assistant-Backups enthalten.
