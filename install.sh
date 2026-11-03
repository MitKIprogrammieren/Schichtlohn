#!/bin/sh
# SchichtLohn-Installer – Synology (Container Manager), Raspberry Pi oder jeder Linux-Rechner mit Docker.
#
#   curl -fsSL https://raw.githubusercontent.com/MitKIprogrammieren/Schichtlohn/main/install.sh | sudo sh
#
# Legt einen Ordner „schichtlohn“ an (Synology: im Freigabeordner „docker“, sonst /opt/schichtlohn), schreibt docker-compose.yml,
# startet den SchichtLohn-Server (auf Wunsch mit Tailscale für den Zugriff von unterwegs und Tailscale Funnel nur für die
# Claude-Adresse), übernimmt auf Wunsch die Daten eines bestehenden SchichtLohn-Servers und richtet ein nächtliches Update ein.
# Der Installer enthält keine Daten und keine Zugänge – nichts davon geht über das Internet, außer dem Laden der Programme.
#
# Ohne Rückfragen (z. B. für Skripte): Antworten als Umgebungsvariablen, etwa
#   SL_TAILSCALE=n SL_PREISE=1 SL_SCHLUESSEL=j SL_ALT="" sh install.sh
set -u

VERSION_INST="1.0"
IMAGE="ghcr.io/mitkiprogrammieren/schichtlohn-server:latest"
PORT=8093

# ---------------------------------------------------------------- Ausgabe
if [ -t 1 ]; then G=$(printf '\033[32m'); D=$(printf '\033[2m'); Y=$(printf '\033[33m'); R=$(printf '\033[31m'); W=$(printf '\033[1m'); N=$(printf '\033[0m')
else G=""; D=""; Y=""; R=""; W=""; N=""; fi
ok()   { printf '  %s✓%s %s\n' "$G" "$N" "$*"; }
info() { printf '  %s%s%s\n' "$D" "$*" "$N"; }
warn() { printf '  %s!%s %s\n' "$Y" "$N" "$*"; }
stopp(){ printf '\n  %s✗ %s%s\n\n' "$R" "$*" "$N"; exit 1; }
teil() { printf '\n%s%s%s\n' "$W" "$*" "$N"; }

# Fragen kommen vom Terminal, auch wenn das Skript per „curl … | sh“ läuft
TTY=""
if [ -r /dev/tty ] && ( : </dev/tty ) 2>/dev/null; then TTY=/dev/tty; fi
frage() {  # frage VARIABLE "Text" "Vorschlag" [geheim]
  _var=$1; _txt=$2; _std=$3
  eval "_vor=\${$_var-__leer__}"
  if [ "$_vor" != "__leer__" ]; then return; fi   # schon per Umgebungsvariable gesetzt
  if [ -z "$TTY" ]; then eval "$_var=\$_std"; return; fi
  if [ -n "$_std" ]; then printf '  %s %s[%s]%s: ' "$_txt" "$D" "$_std" "$N" >/dev/tty; else printf '  %s: ' "$_txt" >/dev/tty; fi
  if [ "${4:-}" = geheim ]; then stty -echo </dev/tty 2>/dev/null; IFS= read -r _a </dev/tty; stty echo </dev/tty 2>/dev/null; printf '\n' >/dev/tty
  else IFS= read -r _a </dev/tty; fi
  [ -z "$_a" ] && _a=$_std
  eval "$_var=\$_a"
}
ja() { case "$1" in j|J|ja|Ja|JA|y|Y|yes) return 0;; *) return 1;; esac; }
json() { printf '%s' "$1" | sed 's/\\/\\\\/g; s/"/\\"/g'; }

printf '\n  %s███ SchichtLohn%s %s· Installer %s für Synology, Raspberry Pi und jeden Linux-Rechner mit Docker%s\n' "$G" "$N" "$D" "$VERSION_INST" "$N"

# ---------------------------------------------------------------- 1. Prüfen
teil "1/5  Prüfen"
[ "$(id -u)" = 0 ] || stopp "Bitte mit Administratorrechten starten: … | sudo sh"

SYNO=""
if [ -f /etc.defaults/VERSION ]; then
  SYNO=$(. /etc.defaults/VERSION 2>/dev/null; printf 'DSM %s.%s' "${majorversion:-?}" "${minorversion:-?}")
  MODELL=$(cat /proc/sys/kernel/syno_hw_version 2>/dev/null || true)
  ok "Synology ${MODELL:+$MODELL · }$SYNO"
else
  ok "$(uname -s) $(uname -m)$( [ -f /etc/os-release ] && . /etc/os-release && printf ' · %s' "${PRETTY_NAME:-}")"
fi

PATH="$PATH:/usr/local/bin:/usr/syno/bin"
command -v docker >/dev/null 2>&1 || {
  [ -n "$SYNO" ] && stopp "Docker fehlt – im Paket-Zentrum „Container Manager“ installieren und den Installer erneut starten."
  stopp "Docker fehlt – installieren mit:  curl -fsSL https://get.docker.com | sh"
}
if docker compose version >/dev/null 2>&1; then DC="docker compose"
elif command -v docker-compose >/dev/null 2>&1; then DC="docker-compose"
else stopp "Docker Compose fehlt (docker compose oder docker-compose)."; fi
ok "Docker $(docker version --format '{{.Server.Version}}' 2>/dev/null || echo '?') · $DC"
command -v curl >/dev/null 2>&1 || stopp "curl fehlt."

# Speicherort
if [ -n "${SL_ORDNER:-}" ]; then ORDNER=$SL_ORDNER
elif [ -n "$SYNO" ]; then
  ORDNER=""
  for v in /volume*/docker; do [ -d "$v" ] && { ORDNER="$v/schichtlohn"; break; }; done
  [ -n "$ORDNER" ] || stopp "Kein Freigabeordner „docker“ gefunden – den legt der Container Manager beim ersten Start an."
else ORDNER=/opt/schichtlohn; fi
mkdir -p "$ORDNER" || stopp "Ordner $ORDNER lässt sich nicht anlegen."
FREI=$(df -h "$ORDNER" 2>/dev/null | awk 'NR==2{print $4}')
ok "Speicherort: $ORDNER ${FREI:+ ${D}($FREI frei)${N}}"

LAEUFT=""
docker ps --format '{{.Names}}' 2>/dev/null | grep -qx schichtlohn && LAEUFT=1
if [ -n "$LAEUFT" ]; then warn "SchichtLohn läuft hier schon – wird mit den vorhandenen Daten neu eingerichtet."
elif (netstat -tln 2>/dev/null || ss -tln 2>/dev/null) | grep -q "[:.]$PORT[[:space:]]"; then stopp "Port $PORT ist belegt."
else ok "Port $PORT ist frei"; fi

# ---------------------------------------------------------------- 2. Fragen
teil "2/5  Fragen  ${D}(Enter = Vorschlag übernehmen)${N}"
frage SL_TAILSCALE "Von unterwegs erreichbar machen (Tailscale)? [j/n]" "j"
TS_KEY=""; FUNNEL=n
if ja "$SL_TAILSCALE"; then
  if [ -f "$ORDNER/tailscale/tailscaled.state" ]; then info "Tailscale ist hier schon angemeldet."
  else frage SL_TS_KEY "Tailscale-Schlüssel (tskey-auth-…, unter login.tailscale.com → Settings → Keys)" "" geheim; TS_KEY=$SL_TS_KEY
       [ -n "$TS_KEY" ] || { warn "Ohne Schlüssel kein Tailscale."; SL_TAILSCALE=n; }; fi
  if ja "$SL_TAILSCALE"; then frage SL_FUNNEL "Claude-Anbindung auch aus dem Internet (für claude.ai und das Handy)? [j/n]" "n"; FUNNEL=$SL_FUNNEL; fi
fi

printf '  Preise aus dem Internet – welche Quellen?  %s(Zahlen mit Komma)%s\n' "$D" "$N" >&2
printf '    %s1)%s Shoppreise: 3DJake, Herstellershops, 3D Prima, iGo3D  %s– ohne Konto%s\n' "$W" "$N" "$D" "$N" >&2
printf '    %s2)%s eBay        %s– braucht einen eigenen eBay-Entwicklerzugang%s\n' "$W" "$N" "$D" "$N" >&2
printf '    %s3)%s AliExpress  %s– braucht einen eigenen AliExpress-Partnerzugang%s\n' "$W" "$N" "$D" "$N" >&2
printf '    %s0)%s keine Preise aus dem Internet\n' "$W" "$N" >&2
frage SL_PREISE "Auswahl" "1"
P_SHOP=false; P_EBAY=""; P_ALI=""
case ",$(printf '%s' "$SL_PREISE" | tr -d ' ')," in *,1,*) P_SHOP=true;; esac
case ",$(printf '%s' "$SL_PREISE" | tr -d ' ')," in *,2,*) P_EBAY=1;; esac
case ",$(printf '%s' "$SL_PREISE" | tr -d ' ')," in *,3,*) P_ALI=1;; esac
EBAY_ID=""; EBAY_SEC=""; ALI_KEY=""; ALI_SEC=""; ALI_TR=""
if [ -n "$P_EBAY" ]; then
  frage SL_EBAY_ID "eBay App-ID (Client ID) – leer = später in der App eintragen" ""; EBAY_ID=$SL_EBAY_ID
  [ -n "$EBAY_ID" ] && { frage SL_EBAY_SECRET "eBay Cert-ID (Client Secret)" "" geheim; EBAY_SEC=$SL_EBAY_SECRET; }
fi
if [ -n "$P_ALI" ]; then
  frage SL_ALI_KEY "AliExpress App Key – leer = später in der App eintragen" ""; ALI_KEY=$SL_ALI_KEY
  [ -n "$ALI_KEY" ] && { frage SL_ALI_SECRET "AliExpress App Secret" "" geheim; ALI_SEC=$SL_ALI_SECRET
                         frage SL_ALI_TRACKING "AliExpress Tracking-ID (optional)" ""; ALI_TR=$SL_ALI_TRACKING; }
fi

frage SL_SCHLUESSEL "Zugangsschlüssel für den Server erzeugen? [j/n]" "j"
frage SL_ALT "Daten von einem bestehenden SchichtLohn übernehmen? Adresse oder leer" ""
ALT_TOK=""; NUR_DATEN=false
if [ -n "$SL_ALT" ]; then
  frage SL_ALT_TOKEN "Schlüssel des alten Servers (leer, wenn keiner)" "" geheim; ALT_TOK=$SL_ALT_TOKEN
  printf '  Was übernehmen?\n    %s1)%s Alles, auch Zugänge (eBay, AliExpress, Bambu, Telegram) %s– für deinen eigenen Umzug%s\n    %s2)%s Nur Lager, Drucke und Preise %s– ohne Zugänge%s\n' "$W" "$N" "$D" "$N" "$W" "$N" "$D" "$N" >&2
  frage SL_ALT_ART "Auswahl" "1"
  [ "$SL_ALT_ART" = 2 ] && NUR_DATEN=true
fi

# ---------------------------------------------------------------- 3. Einrichten
teil "3/5  Einrichten"
mkdir -p "$ORDNER/daten" && ok "Ordner daten/ angelegt"
DIENST_TS=""
if ja "$SL_TAILSCALE"; then
  mkdir -p "$ORDNER/tailscale" "$ORDNER/tailscale-config"
  # Port 443: ganze App, nur im eigenen Tailscale-Netz. Port 8443: nur /mcp/ – auf Wunsch per Funnel aus dem Internet.
  if ja "$FUNNEL"; then FUN=',"AllowFunnel":{"${TS_CERT_DOMAIN}:8443":true}'; else FUN=""; fi
  cat >"$ORDNER/tailscale-config/serve.json" <<EOF
{"TCP":{"443":{"HTTPS":true},"8443":{"HTTPS":true}},
 "Web":{"\${TS_CERT_DOMAIN}:443":{"Handlers":{"/":{"Proxy":"http://127.0.0.1:$PORT"}}},
        "\${TS_CERT_DOMAIN}:8443":{"Handlers":{"/mcp/":{"Proxy":"http://127.0.0.1:$PORT/mcp/"}}}}$FUN}
EOF
  DIENST_TS="  tailscale:
    image: tailscale/tailscale:stable
    container_name: schichtlohn-tailscale
    hostname: schichtlohn
    environment:
      - TS_AUTHKEY=${TS_KEY}
      - TS_HOSTNAME=schichtlohn
      - TS_STATE_DIR=/var/lib/tailscale
      - TS_SERVE_CONFIG=/config/serve.json
      - TS_USERSPACE=true
      - TS_ACCEPT_DNS=false
    volumes:
      - $ORDNER/tailscale:/var/lib/tailscale
      - $ORDNER/tailscale-config:/config:ro
    ports:
      - \"$PORT:$PORT\"
    restart: unless-stopped
"
  NETZ="    network_mode: service:tailscale
    depends_on:
      - tailscale"
else
  NETZ="    ports:
      - \"$PORT:$PORT\""
fi
cat >"$ORDNER/docker-compose.yml" <<EOF
# Angelegt vom SchichtLohn-Installer $VERSION_INST am $(date '+%d.%m.%Y %H:%M'). Daten liegen in daten/.
services:
$DIENST_TS  schichtlohn:
    image: $IMAGE
    container_name: schichtlohn
$NETZ
    volumes:
      - $ORDNER/daten:/daten
    environment:
      - TZ=${TZ:-Europe/Berlin}
    pull_policy: always
    init: true
    stop_grace_period: 5s
    restart: unless-stopped
    mem_limit: 2g
EOF
chmod 600 "$ORDNER/docker-compose.yml"
ok "docker-compose.yml${DIENST_TS:+ und serve.json} geschrieben"

cat >"$ORDNER/schichtlohn.sh" <<EOF
#!/bin/sh
# SchichtLohn verwalten:  sh $ORDNER/schichtlohn.sh  status | update | neustart | stopp | entfernen
cd "$ORDNER" || exit 1
case "\${1:-status}" in
  update)    $DC -p schichtlohn pull -q && $DC -p schichtlohn up -d --remove-orphans && docker image prune -f >/dev/null 2>&1
             echo "\$(date '+%Y-%m-%d %H:%M') aktualisiert" >> "$ORDNER/update.log";;
  neustart)  $DC -p schichtlohn restart;;
  stopp)     $DC -p schichtlohn stop;;
  entfernen) $DC -p schichtlohn down && echo "Entfernt. Deine Daten liegen weiter in $ORDNER/daten.";;
  *)         $DC -p schichtlohn ps; curl -s -m 5 http://127.0.0.1:$PORT/status; echo;;
esac
EOF
chmod 755 "$ORDNER/schichtlohn.sh"

printf '  %s↓%s Lade SchichtLohn-Server … ' "$G" "$N"
cd "$ORDNER" || stopp "Ordner nicht erreichbar"
$DC -p schichtlohn pull -q >/tmp/schichtlohn-pull.log 2>&1 || { printf '\n'; cat /tmp/schichtlohn-pull.log; stopp "Laden fehlgeschlagen."; }
printf '%sfertig%s\n' "$G" "$N"
$DC -p schichtlohn up -d --remove-orphans >/tmp/schichtlohn-up.log 2>&1 || { cat /tmp/schichtlohn-up.log; stopp "Start fehlgeschlagen."; }
B="http://127.0.0.1:$PORT"
i=0; until curl -s -m 3 "$B/status" | grep -q schichtlohn-server; do i=$((i+1)); [ $i -gt 60 ] && stopp "Server antwortet nicht – Protokoll: docker logs schichtlohn"; sleep 2; done
VER=$(curl -s -m 3 "$B/status" | sed -n 's/.*"version": *"\([^"]*\)".*/\1/p')
ok "Container gestartet · SchichtLohn ${VER:-?}"
TS_NAME=""
if ja "$SL_TAILSCALE"; then
  i=0; while [ $i -lt 30 ]; do
    TS_NAME=$(docker exec schichtlohn-tailscale tailscale status --json --peers=false 2>/dev/null | sed -n 's/.*"DNSName": *"\([^"]*\)\.".*/\1/p' | head -1)
    [ -n "$TS_NAME" ] && break; i=$((i+1)); sleep 2; done
  if [ -n "$TS_NAME" ]; then ok "Tailscale angemeldet als ${W}${TS_NAME%%.*}${N}"
    # Schlüssel nach der Anmeldung nicht mehr im Klartext liegen lassen
    sed -i 's/^\(      - TS_AUTHKEY=\).*/\1/' "$ORDNER/docker-compose.yml" 2>/dev/null
  else warn "Tailscale noch nicht angemeldet – Protokoll: docker logs schichtlohn-tailscale"; fi
fi

# ---------------------------------------------------------------- 4. Daten übernehmen
teil "4/5  Daten übernehmen"
if [ -n "$SL_ALT" ]; then
  A=$(curl -s -m 600 -X POST "$B/api/umzug" -H 'Content-Type: application/json' \
      -d "{\"quelle\":\"$(json "$SL_ALT")\",\"token\":\"$(json "$ALT_TOK")\",\"nur_daten\":$NUR_DATEN}")
  if printf '%s' "$A" | grep -q '"listen"'; then
    SORTEN=$(printf '%s' "$A" | sed -n 's/.*"todo.filament": *\([0-9]*\).*/\1/p'); BUCH=$(printf '%s' "$A" | sed -n 's/.*"todo.filament_verbrauch": *\([0-9]*\).*/\1/p')
    if [ "$NUR_DATEN" = true ]; then ok "${SORTEN:-0} Einträge im Lager, ${BUCH:-0} Buchungen, Drucke und Preise übernommen"
    else ok "${SORTEN:-0} Einträge im Lager, ${BUCH:-0} Buchungen, Drucke, Einstellungen und Zugänge übernommen"; fi
    [ "$NUR_DATEN" = true ] && info "– Zugänge nicht übernommen (eBay, AliExpress, Bambu, Telegram selbst eintragen: Einstellungen)"
    $DC -p schichtlohn restart schichtlohn >/dev/null 2>&1; sleep 3
    i=0; until curl -s -m 3 "$B/status" | grep -q schichtlohn-server; do i=$((i+1)); [ $i -gt 30 ] && break; sleep 2; done
  else warn "Übernahme fehlgeschlagen: $(printf '%s' "$A" | sed -n 's/.*"fehler": *"\([^"]*\)".*/\1/p')"
       info "Nachholen in der App: Einstellungen → SchichtLohn-Server → Umzug"; fi
else info "Nichts zu übernehmen – SchichtLohn startet mit leerem Lager."; fi

SCHL=""; ja "$SL_SCHLUESSEL" && SCHL="erzeugen"
E=$(curl -s -m 20 -X POST "$B/api/einrichten" -H 'Content-Type: application/json' \
    -d "{\"schluessel\":\"$SCHL\",\"preise\":{\"shop\":$P_SHOP,\"ebay\":{\"id\":\"$(json "$EBAY_ID")\",\"secret\":\"$(json "$EBAY_SEC")\"},\"ali\":{\"key\":\"$(json "$ALI_KEY")\",\"secret\":\"$(json "$ALI_SEC")\",\"tracking\":\"$(json "$ALI_TR")\"}}}")
TOKEN=$(printf '%s' "$E" | sed -n 's/.*"token": *"\([^"]*\)".*/\1/p')
MCP=$(printf '%s' "$E" | sed -n 's/.*"mcp": *"\([^"]*\)".*/\1/p')
printf '%s' "$E" | grep -q '"ok": *true' || warn "Einstellungen ließen sich nicht setzen: $E"

# ---------------------------------------------------------------- 5. Aktuell halten
teil "5/5  Aktuell halten"
ZEILE="10 4 * * * root sh $ORDNER/schichtlohn.sh update >/dev/null 2>&1"
if [ -n "$SYNO" ]; then
  if ! grep -q "schichtlohn.sh update" /etc/crontab 2>/dev/null; then printf '10\t4\t*\t*\t*\troot\tsh %s/schichtlohn.sh update >/dev/null 2>&1\n' "$ORDNER" >> /etc/crontab; fi
  (synosystemctl restart crond || systemctl restart crond) >/dev/null 2>&1
  ok "Nächtliches Update um 04:10 eingetragen"
  info "Falls es nach einem DSM-Update fehlt: Systemsteuerung → Aufgabenplanung → Benutzerdefiniertes Script: sh $ORDNER/schichtlohn.sh update"
elif [ -d /etc/cron.d ]; then printf '%s\n' "$ZEILE" > /etc/cron.d/schichtlohn; ok "Nächtliches Update um 04:10 eingetragen (/etc/cron.d/schichtlohn)"
else warn "Kein cron gefunden – Update von Hand: sh $ORDNER/schichtlohn.sh update"; fi

# ---------------------------------------------------------------- Ergebnis
IP=$(ip -4 route get 1.1.1.1 2>/dev/null | sed -n 's/.* src \([0-9.]*\).*/\1/p'); [ -n "$IP" ] || IP=$(hostname -I 2>/dev/null | awk '{print $1}')
printf '\n%s━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━%s\n' "$G" "$N"
printf '  %sSchichtLohn läuft.%s\n\n' "$W" "$N"
printf '  Im Heimnetz     http://%s:%s/app/\n' "${IP:-IP-DIESES-RECHNERS}" "$PORT"
[ -n "$TS_NAME" ] && printf '  Von unterwegs   https://%s/app/   %s(nur in deinem Tailscale-Netz)%s\n' "$TS_NAME" "$D" "$N"
if [ -n "$MCP" ]; then
  if [ -n "$TS_NAME" ] && ja "$FUNNEL"; then printf '  Claude (MCP)    https://%s:8443%s\n' "$TS_NAME" "$MCP"
    info "                → in Claude: Einstellungen → Konnektoren → Eigenen Konnektor hinzufügen"
    info "                Funnel muss im Tailscale-Konto erlaubt sein (login.tailscale.com → Access controls → Funnel)"
  elif [ -n "$TS_NAME" ]; then printf '  Claude (MCP)    https://%s:8443%s   %s(Desktop/Code im Tailscale-Netz)%s\n' "$TS_NAME" "$MCP" "$D" "$N"
  else printf '  Claude (MCP)    http://%s:%s%s   %s(nur im Heimnetz)%s\n' "${IP:-IP}" "$PORT" "$MCP" "$D" "$N"; fi
  info "                Wer diese Adresse kennt, kann dein Lager ändern – nicht weitergeben."
fi
PR=""; [ "$P_SHOP" = true ] && PR="Shoppreise an" || PR="Shoppreise aus"
[ -n "$P_EBAY" ] && { [ -n "$EBAY_SEC" ] && PR="$PR · eBay an" || PR="$PR · eBay an (Zugang fehlt)"; } || PR="$PR · eBay aus"
[ -n "$P_ALI" ] && { [ -n "$ALI_SEC" ] && PR="$PR · AliExpress an" || PR="$PR · AliExpress an (Zugang fehlt)"; } || PR="$PR · AliExpress aus"
printf '  Preise          %s\n' "$PR"
if [ -n "$TOKEN" ]; then printf '  Schlüssel       %s%s%s  %s(nur jetzt ganz angezeigt – ändern: Einstellungen → Zugang)%s\n' "$Y" "$TOKEN" "$N" "$D" "$N"
elif ja "$SL_SCHLUESSEL"; then info "  Schlüssel       war schon gesetzt – bleibt wie er ist"; fi
printf '\n  Verwalten:  sh %s/schichtlohn.sh  status | update | neustart | entfernen  %s(Daten bleiben)%s\n\n' "$ORDNER" "$D" "$N"
