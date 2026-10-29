#!/bin/sh
# SchichtLohn-Server auf den neuesten Stand bringen (neues Image holen, Container neu starten).
# Synology: Systemsteuerung → Aufgabenplanung → Erstellen → Geplante Aufgabe → Benutzerdefiniertes Script,
# Benutzer: root, täglich nachts, Befehl:  sh /volume1/docker/schichtlohn/update.sh
# Daten in docker/schichtlohn/daten bleiben dabei erhalten.
cd "$(dirname "$0")" || exit 1
if docker compose version >/dev/null 2>&1; then DC="docker compose"; else DC="docker-compose"; fi
$DC -p schichtlohn pull --quiet && $DC -p schichtlohn up -d --remove-orphans
docker image prune -f >/dev/null 2>&1
echo "$(date '+%Y-%m-%d %H:%M') SchichtLohn aktualisiert" >> "$(dirname "$0")/update.log"
