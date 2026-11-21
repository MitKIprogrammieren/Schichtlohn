#!/usr/bin/env python3
"""Piwerk – Status und Updates der Raspberry Pis für die Werke-Startseite.

Läuft als Stack „piwerk“ auf dem NUC. Verbindet sich per SSH-Schlüssel mit den Pis,
sammelt alle paar Sekunden CPU, Temperatur, RAM, Speicher und anstehende Updates
und führt auf Knopfdruck apt-Updates, Container-Updates und Neustarts aus.
Werke erreicht den Dienst über /pi/ (nginx leitet weiter).
"""
import base64
import fcntl
import hashlib
import json
import os
import pty
import struct
import termios
import re
import socket
import subprocess
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

DATEN = os.environ.get("DATEN", "/daten")
PORT = int(os.environ.get("PORT", "8085"))
SCHLUESSEL = os.path.join(DATEN, "id_ed25519")
BEKANNT = os.path.join(DATEN, "known_hosts")
KONFIG = os.path.join(DATEN, "pis.json")
INTERVALL = 15            # Sekunden zwischen Statusabfragen
APT_INTERVALL = 6 * 3600  # Paketlisten alle 6 Stunden auffrischen

START_PIS = [
    {"id": "nextcloud", "name": "Nextcloud", "host": "192.168.1.140", "user": "pi", "url": "https://192.168.1.140/"},
    {"id": "pihole", "name": "Pi-hole", "host": "192.168.1.250", "user": "pi", "url": "http://192.168.1.250/admin/"},
    {"id": "immich", "name": "Immich", "host": "", "user": "pi", "url": ""},
]

STATUS_SKRIPT = r"""
read -r _ a b c d e f g h _ < /proc/stat
sleep 0.5
read -r _ a2 b2 c2 d2 e2 f2 g2 h2 _ < /proc/stat
t=$(( (a2+b2+c2+d2+e2+f2+g2+h2) - (a+b+c+d+e+f+g+h) )); i=$(( (d2+e2) - (d+e) ))
[ "$t" -gt 0 ] && echo "cpu=$(( 100 * (t - i) / t ))"
echo "temp=$(cat /sys/class/thermal/thermal_zone0/temp 2>/dev/null)"
awk '/^MemTotal/{t=$2}/^MemAvailable/{a=$2}END{print "ram="(t-a)"/"t}' /proc/meminfo
df -Pk / | awk 'NR==2{print "disk="$3"/"$2}'
echo "uptime=$(cut -d. -f1 /proc/uptime)"
echo "modell=$(tr -d '\0' < /proc/device-tree/model 2>/dev/null)"
. /etc/os-release 2>/dev/null; echo "os=$PRETTY_NAME"
echo "name=$(hostname)"
LC_ALL=C apt-get -s -o Debug::NoLocking=1 dist-upgrade 2>/dev/null | grep '^Inst ' | sed 's/^/paket=/' 
[ -f /var/run/reboot-required ] && echo neustart=1 || echo neustart=0
command -v docker >/dev/null 2>&1 && echo docker=1 || echo docker=0
sudo -n -l /usr/bin/apt-get >/dev/null 2>&1 && echo sudo=1 || echo sudo=0
"""

SKRIPTE = {
    "update": r"""exec 2>&1
set -e
A="sudo -n DEBIAN_FRONTEND=noninteractive apt-get"
echo ">> Paketlisten holen"
$A update
echo ">> Updates einspielen"
$A -y -o Dpkg::Options::=--force-confdef -o Dpkg::Options::=--force-confold dist-upgrade
echo ">> Aufräumen"
$A -y autoremove
if [ -f /var/run/reboot-required ]; then echo ">> Fertig – Neustart nötig"; else echo ">> Fertig – kein Neustart nötig"; fi
""",
    "pruefen": r"""exec 2>&1
sudo -n apt-get update
echo ">> $(apt-get -s dist-upgrade 2>/dev/null | grep -c '^Inst') Updates verfügbar"
""",
    "neustart": r"""exec 2>&1
echo ">> Pi startet neu …"
sudo -n systemctl reboot
""",
    "container": r"""exec 2>&1
D=docker; docker info >/dev/null 2>&1 || D="sudo -n docker"
LISTE=$($D compose ls -a --format json 2>/dev/null | python3 -c 'import sys, json
for p in json.load(sys.stdin): print(p["Name"] + "|" + p["ConfigFiles"])' 2>/dev/null)
if [ -z "$LISTE" ]; then echo ">> Keine Compose-Projekte gefunden"; exit 0; fi
echo "$LISTE" | while IFS='|' read -r NAME DATEIEN; do
  echo ">> $NAME"
  ARGS=""
  OLDIFS=$IFS; IFS=,; for F in $DATEIEN; do ARGS="$ARGS -f $F"; done; IFS=$OLDIFS
  $D compose -p "$NAME" $ARGS pull && $D compose -p "$NAME" $ARGS up -d || echo ">> Fehler bei $NAME"
done
echo ">> Alte Images entfernen"
$D image prune -f
echo ">> Fertig"
""",
}

sperre = threading.Lock()
PIS = []
STATUS = {}
JOBS = {}
LAUFEND = {}
APT_ZULETZT = {}


def lade_konfig():
    global PIS
    try:
        with open(KONFIG) as f:
            PIS = json.load(f)
    except Exception:
        PIS = [dict(p) for p in START_PIS]
        speichere_konfig()


def speichere_konfig():
    tmp = KONFIG + ".tmp"
    with open(tmp, "w") as f:
        json.dump(PIS, f, indent=2, ensure_ascii=False)
    os.replace(tmp, KONFIG)


def schluessel_anlegen():
    if not os.path.exists(SCHLUESSEL):
        subprocess.run(["ssh-keygen", "-t", "ed25519", "-N", "", "-C", "piwerk@nuc", "-f", SCHLUESSEL],
                       check=True, stdout=subprocess.DEVNULL)
    os.chmod(SCHLUESSEL, 0o600)


def oeffentlicher_schluessel():
    try:
        with open(SCHLUESSEL + ".pub") as f:
            return f.read().strip()
    except Exception:
        return ""


def ssh_basis(pi):
    return ["ssh", "-i", SCHLUESSEL, "-o", "BatchMode=yes", "-o", "ConnectTimeout=5",
            "-o", "StrictHostKeyChecking=accept-new", "-o", f"UserKnownHostsFile={BEKANNT}",
            "-o", "ServerAliveInterval=15", "-o", "LogLevel=ERROR"]


def ssh_befehl(pi):
    return ssh_basis(pi) + [f"{pi['user']}@{pi['host']}", "bash", "-s"]


# ---------- Terminal im Browser (wie Raspberry Pi Connect Lite) ----------
WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


def ws_lesen(rf):
    """Einen WebSocket-Rahmen lesen → (opcode, daten) oder (None, None) bei Verbindungsende."""
    kopf = rf.read(2)
    if len(kopf) < 2:
        return None, None
    op, maskiert, n = kopf[0] & 0x0F, kopf[1] & 0x80, kopf[1] & 0x7F
    if n == 126:
        n = struct.unpack(">H", rf.read(2))[0]
    elif n == 127:
        n = struct.unpack(">Q", rf.read(8))[0]
    maske = rf.read(4) if maskiert else None
    daten = rf.read(n)
    if maske:
        daten = bytes(b ^ maske[i & 3] for i, b in enumerate(daten))
    return op, daten


def ws_senden(wf, op, daten=b""):
    n = len(daten)
    if n < 126:
        kopf = struct.pack(">BB", 0x80 | op, n)
    elif n < 65536:
        kopf = struct.pack(">BBH", 0x80 | op, 126, n)
    else:
        kopf = struct.pack(">BBQ", 0x80 | op, 127, n)
    wf.write(kopf + daten)
    wf.flush()


def fenstergroesse(fd, zeilen, spalten):
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", max(5, zeilen), max(20, spalten), 0, 0))


def terminal_sitzung(handler, pi):
    """Verbindet einen WebSocket mit einer SSH-Sitzung (mit echtem Terminal) auf dem Pi."""
    master, slave = pty.openpty()
    fenstergroesse(slave, 30, 100)

    def vorher():
        os.setsid()
        fcntl.ioctl(0, termios.TIOCSCTTY, 0)

    p = subprocess.Popen(ssh_basis(pi) + ["-tt", f"{pi['user']}@{pi['host']}"],
                         stdin=slave, stdout=slave, stderr=slave, preexec_fn=vorher, close_fds=True,
                         env={**os.environ, "TERM": "xterm-256color", "LANG": "C.UTF-8"})
    os.close(slave)
    sperre_senden = threading.Lock()

    def senden(op, daten=b""):
        with sperre_senden:
            ws_senden(handler.wfile, op, daten)

    def ausgabe():
        try:
            while True:
                try:
                    d = os.read(master, 65536)
                except OSError:
                    break
                if not d:
                    break
                senden(2, d)
        except (OSError, ConnectionError):
            pass
        finally:
            try:
                senden(8)
            except Exception:  # noqa: BLE001
                pass

    threading.Thread(target=ausgabe, daemon=True).start()
    try:
        while True:
            op, d = ws_lesen(handler.rfile)
            if op is None or op == 8:
                break
            if op == 9:
                senden(10, d)
            elif op in (1, 2) and d:
                if d[:1] == b"1":
                    try:
                        j = json.loads(d[1:])
                        fenstergroesse(master, int(j["r"]), int(j["c"]))
                    except Exception:  # noqa: BLE001
                        pass
                else:
                    rest = d[1:]
                    while rest:
                        rest = rest[os.write(master, rest):]
    except (OSError, ConnectionError, struct.error):
        pass
    finally:
        p.terminate()
        try:
            p.wait(3)
        except subprocess.TimeoutExpired:
            p.kill()
        try:
            os.close(master)
        except OSError:
            pass


def port_offen(host, port=22):
    try:
        with socket.create_connection((host, port), timeout=2):
            return True
    except OSError:
        return False


def zahl(s):
    try:
        return int(s)
    except (TypeError, ValueError):
        return None


PAKET_MUSTER = re.compile(r"^Inst (\S+) (?:\[([^\]]*)\] )?\((\S+) ([^ \[)]*)")


def paket_lesen(zeile):
    """Eine Zeile wie 'Inst curl [7.88.1-10+deb12u8] (7.88.1-10+deb12u12 Debian-Security:12/stable-security [arm64])'."""
    m = PAKET_MUSTER.match(zeile)
    if not m:
        return None
    return {"name": m.group(1), "alt": m.group(2) or "", "neu": m.group(3),
            "sicherheit": "security" in m.group(4).lower()}


def frage_ab(pi):
    """Status eines Pis abfragen und in STATUS ablegen."""
    alt = STATUS.get(pi["id"], {})
    if not pi.get("host"):
        STATUS[pi["id"]] = {"zustand": "ohne_ip", "zuletzt": alt.get("zuletzt")}
        return
    try:
        r = subprocess.run(ssh_befehl(pi), input=STATUS_SKRIPT, capture_output=True, text=True, timeout=25)
    except subprocess.TimeoutExpired:
        r = None
    if r is None or r.returncode == 255:
        fehler = (r.stderr.strip() if r else "Zeitüberschreitung")[-300:]
        zustand = "kein_zugang" if port_offen(pi["host"]) else "offline"
        STATUS[pi["id"]] = {"zustand": zustand, "fehler": fehler, "zuletzt": alt.get("zuletzt")}
        return
    zeilen = r.stdout.splitlines()
    w = dict(z.split("=", 1) for z in zeilen if "=" in z and not z.startswith("paket="))
    pakete = [p for p in (paket_lesen(z[6:]) for z in zeilen if z.startswith("paket=")) if p]
    ram = [zahl(x) for x in w.get("ram", "/").split("/")]
    disk = [zahl(x) for x in w.get("disk", "/").split("/")]
    temp = zahl(w.get("temp"))
    STATUS[pi["id"]] = {
        "zustand": "online",
        "zuletzt": time.time(),
        "cpu": zahl(w.get("cpu")),
        "temp": round(temp / 1000, 1) if temp else None,
        "ram": ram if None not in ram else None,      # kB benutzt / gesamt
        "disk": disk if None not in disk else None,   # kB benutzt / gesamt
        "uptime": zahl(w.get("uptime")),
        "modell": w.get("modell", ""),
        "os": w.get("os", ""),
        "name": w.get("name", ""),
        "updates": len(pakete),
        "pakete": pakete,
        "sicherheit": sum(1 for p in pakete if p["sicherheit"]),
        "neustart": w.get("neustart") == "1",
        "docker": w.get("docker") == "1",
        "sudo": w.get("sudo") == "1",
    }
    # Paketlisten ab und zu im Hintergrund auffrischen, damit die Update-Zahl stimmt
    if STATUS[pi["id"]]["sudo"] and time.time() - APT_ZULETZT.get(pi["id"], 0) > APT_INTERVALL \
            and not job_laeuft(pi["id"]):
        APT_ZULETZT[pi["id"]] = time.time()
        threading.Thread(target=apt_auffrischen, args=(pi,), daemon=True).start()


def apt_auffrischen(pi):
    try:
        subprocess.run(ssh_befehl(pi), input="sudo -n apt-get update -qq", capture_output=True,
                       text=True, timeout=300)
    except subprocess.TimeoutExpired:
        pass


def status_schleife():
    while True:
        with sperre:
            liste = [dict(p) for p in PIS]
        ts = [threading.Thread(target=frage_ab, args=(p,), daemon=True) for p in liste if not job_laeuft(p["id"])]
        for t in ts:
            t.start()
        for t in ts:
            t.join(60)
        time.sleep(INTERVALL)


def job_laeuft(pid):
    jid = LAUFEND.get(pid)
    return bool(jid and not JOBS[jid]["fertig"])


def finde_pi(pid):
    with sperre:
        for p in PIS:
            if p["id"] == pid:
                return dict(p)
    return None


def starte_job(pi, art):
    if job_laeuft(pi["id"]):
        return LAUFEND[pi["id"]]
    jid = uuid.uuid4().hex[:10]
    job = {"id": jid, "pi": pi["id"], "name": pi["name"], "art": art, "zeilen": [],
           "fertig": False, "ok": None, "start": time.time()}
    JOBS[jid] = job
    LAUFEND[pi["id"]] = jid
    if pi["id"] in STATUS:
        STATUS[pi["id"]]["job"] = art

    def lauf():
        try:
            p = subprocess.Popen(ssh_befehl(pi), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                 stderr=subprocess.STDOUT, text=True, bufsize=1, errors="replace")
            p.stdin.write(SKRIPTE[art])
            p.stdin.close()
            for z in p.stdout:
                z = z.rstrip("\n")
                if z.strip():
                    job["zeilen"].append(z[-400:])
                    if len(job["zeilen"]) > 4000:
                        del job["zeilen"][:500]
            rc = p.wait()
            job["ok"] = rc == 0 or art == "neustart"
            if rc != 0 and art != "neustart":
                job["zeilen"].append(f">> Abgebrochen (Code {rc})")
        except Exception as e:  # noqa: BLE001
            job["zeilen"].append(f">> Fehler: {e}")
            job["ok"] = False
        finally:
            job["fertig"] = True
            job["ende"] = time.time()
            if art == "neustart":
                time.sleep(40)
            frage_ab(pi)

    threading.Thread(target=lauf, daemon=True).start()
    # alte Jobs wegräumen
    for k in [k for k, j in JOBS.items() if j["fertig"] and time.time() - j.get("ende", 0) > 6 * 3600]:
        JOBS.pop(k, None)
    return jid


def liste():
    with sperre:
        pis = [dict(p) for p in PIS]
    for p in pis:
        p["status"] = STATUS.get(p["id"], {"zustand": "unbekannt"})
        p["job"] = LAUFEND.get(p["id"]) if job_laeuft(p["id"]) else None
        p["letzter_job"] = LAUFEND.get(p["id"])
    return {"pis": pis, "zeit": time.time()}


def neue_id(name):
    basis = "".join(c for c in name.lower() if c.isalnum()) or "pi"
    vorhanden = {p["id"] for p in PIS}
    i, kandidat = 2, basis
    while kandidat in vorhanden:
        kandidat = f"{basis}{i}"
        i += 1
    return kandidat


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"   # nötig für WebSocket (101)
    def log_message(self, *a):
        pass

    def antwort(self, daten, code=200):
        body = json.dumps(daten, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def koerper(self):
        n = int(self.headers.get("Content-Length") or 0)
        if not n:
            return {}
        try:
            return json.loads(self.rfile.read(n))
        except Exception:
            return {}

    def teile(self):
        u = urlparse(self.path)
        pfad = u.path
        if pfad.startswith("/pi/"):
            pfad = pfad[3:]
        return [t for t in pfad.split("/") if t], parse_qs(u.query)

    def terminal(self, pid):
        pi = finde_pi(pid)
        schluessel = self.headers.get("Sec-WebSocket-Key")
        if not pi or not pi.get("host") or not schluessel:
            return self.antwort({"fehler": "Pi unbekannt oder keine WebSocket-Anfrage"}, 400)
        antwort = base64.b64encode(hashlib.sha1((schluessel + WS_GUID).encode()).digest()).decode()
        self.close_connection = True
        self.send_response(101, "Switching Protocols")
        self.send_header("Upgrade", "websocket")
        self.send_header("Connection", "Upgrade")
        self.send_header("Sec-WebSocket-Accept", antwort)
        self.end_headers()
        self.wfile.flush()
        terminal_sitzung(self, pi)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        t, q = self.teile()
        if len(t) == 3 and t[:2] == ["api", "terminal"]:
            return self.terminal(t[2])
        if t == ["api", "pis"]:
            return self.antwort(liste())
        if t == ["api", "schluessel"]:
            return self.antwort({"schluessel": oeffentlicher_schluessel()})
        if len(t) == 3 and t[:2] == ["api", "job"]:
            job = JOBS.get(t[2])
            if not job:
                return self.antwort({"fehler": "Unbekannter Auftrag"}, 404)
            ab = zahl((q.get("ab") or ["0"])[0]) or 0
            return self.antwort({k: v for k, v in job.items() if k != "zeilen"} |
                                {"zeilen": job["zeilen"][ab:], "anzahl": len(job["zeilen"])})
        if t in ([], ["api"], ["api", "gesund"]):
            return self.antwort({"ok": True, "dienst": "Piwerk"})
        self.antwort({"fehler": "Nicht gefunden"}, 404)

    def do_POST(self):
        t, _ = self.teile()
        d = self.koerper()
        if t == ["api", "alle"]:
            jobs = {}
            for p in [dict(p) for p in PIS]:
                s = STATUS.get(p["id"], {})
                if s.get("zustand") == "online" and s.get("sudo"):
                    jobs[p["id"]] = starte_job(p, "update")
            return self.antwort({"jobs": jobs})
        if t == ["api", "pis"]:
            name = str(d.get("name", "")).strip()[:40]
            if not name:
                return self.antwort({"fehler": "Name fehlt"}, 400)
            eintrag = {k: str(d.get(k, "")).strip()[:200] for k in ("name", "host", "user", "url")}
            eintrag["user"] = eintrag["user"] or "pi"
            with sperre:
                pid = d.get("id")
                vorhanden = next((p for p in PIS if p["id"] == pid), None)
                if vorhanden:
                    vorhanden.update(eintrag)
                else:
                    eintrag["id"] = neue_id(name)
                    PIS.append(eintrag)
                    pid = eintrag["id"]
                speichere_konfig()
            STATUS.pop(pid, None)
            threading.Thread(target=frage_ab, args=(finde_pi(pid),), daemon=True).start()
            return self.antwort({"ok": True, "id": pid})
        if len(t) == 4 and t[:2] == ["api", "pis"] and t[3] in SKRIPTE:
            pi = finde_pi(t[2])
            if not pi or not pi.get("host"):
                return self.antwort({"fehler": "Pi unbekannt oder ohne IP"}, 404)
            return self.antwort({"job": starte_job(pi, t[3])})
        self.antwort({"fehler": "Nicht gefunden"}, 404)

    def do_DELETE(self):
        t, _ = self.teile()
        if len(t) == 3 and t[:2] == ["api", "pis"]:
            with sperre:
                PIS[:] = [p for p in PIS if p["id"] != t[2]]
                speichere_konfig()
            STATUS.pop(t[2], None)
            return self.antwort({"ok": True})
        self.antwort({"fehler": "Nicht gefunden"}, 404)


if __name__ == "__main__":
    os.makedirs(DATEN, exist_ok=True)
    schluessel_anlegen()
    lade_konfig()
    threading.Thread(target=status_schleife, daemon=True).start()
    print(f"Piwerk läuft auf Port {PORT}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
