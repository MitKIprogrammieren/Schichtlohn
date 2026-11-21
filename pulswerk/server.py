"""Pulswerk – Echtzeit-Auslastung des Proxmox-NUC.

Liefert index.html aus und unter /api/werte die Werte des Host-Messdiensts (sensor.py auf dem
Proxmox-Host), ergänzt um CPU und RAM jedes Docker-Containers in CT 100. Nur lesend."""
import glob
import http.client
import json
import os
import re
import socket
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = int(os.environ.get("PORT", "8088"))
SENSOR = os.environ.get("SENSOR", "http://192.168.1.5:9105/werte")
HTML = os.environ.get("HTML", os.path.join(os.path.dirname(os.path.abspath(__file__)), "index.html"))
CG = os.environ.get("CG", "/cg")
SOCK = "/var/run/docker.sock"
NETZ = os.environ.get("NETZ", "http://127.0.0.1:8098").rstrip("/")
NAMEN = {"zeit": 0, "namen": {}}
ALT = {}
SPERRE = threading.Lock()


class UnixVerbindung(http.client.HTTPConnection):
    def __init__(self):
        super().__init__("localhost", timeout=3)

    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(3)
        self.sock.connect(SOCK)


def docker_namen():
    if time.time() - NAMEN["zeit"] < 30:
        return NAMEN["namen"]
    try:
        c = UnixVerbindung()
        c.request("GET", "/containers/json")
        liste = json.loads(c.getresponse().read())
        NAMEN["namen"] = {x["Id"]: x["Names"][0].lstrip("/") for x in liste}
    except Exception:
        pass
    NAMEN["zeit"] = time.time()
    return NAMEN["namen"]


def lesen(pfad):
    try:
        with open(pfad) as f:
            return f.read()
    except OSError:
        return ""


def container():
    """CPU (in % des ganzen NUC) und RAM je Docker-Container aus den cgroups."""
    namen = docker_namen()
    jetzt = time.time()
    kerne = os.cpu_count() or 1
    erg = []
    with SPERRE:
        for cid, name in namen.items():
            pfade = glob.glob(f"{CG}/**/docker-{cid}.scope", recursive=True) or glob.glob(f"{CG}/**/{cid}", recursive=True)
            if not pfade:
                continue
            p = pfade[0]
            u = re.search(r"usage_usec (\d+)", lesen(p + "/cpu.stat"))
            usec = int(u.group(1)) if u else 0
            alt = ALT.get(cid)
            cpu = None
            if alt and jetzt > alt[0]:
                cpu = round(max(0, usec - alt[1]) / ((jetzt - alt[0]) * 1e6 * kerne) * 100, 1)
            ALT[cid] = (jetzt, usec)
            ram = lesen(p + "/memory.current").strip()
            erg.append({"name": name, "cpu": cpu, "ram": int(ram) if ram.isdigit() else 0})
    return sorted(erg, key=lambda x: -(x["cpu"] or 0))


# ---------- Verlauf: läuft immer mit, auch wenn keine Seite offen ist ----------
DATEN = os.environ.get("DATEN", "/daten")
VERLAUF_DATEI = os.path.join(DATEN, "verlauf.json")
KURZ = []          # alle 5 s, letzte Stunde: [zeit, cpu, temp, rx, tx]
LANG = []          # je Minute, 30 Tage:     [zeit, cpu, temp, rx, tx, temp_max]
MINUTE = []


def prozessor_temp(t):
    t = [x for x in (t or []) if -20 < x.get("grad", -999) < 130]
    for x in t:
        if "package" in x.get("name", "").lower():
            return x["grad"]
    kerne = [x["grad"] for x in t if x.get("quelle") == "coretemp"]
    return max(kerne) if kerne else None


def verlauf_laden():
    try:
        with open(VERLAUF_DATEI) as f:
            LANG.extend(json.load(f)[-43200:])
    except (OSError, ValueError):
        pass


def verlauf_sichern():
    try:
        os.makedirs(DATEN, exist_ok=True)
        with open(VERLAUF_DATEI + ".tmp", "w") as f:
            json.dump(LANG, f, separators=(",", ":"))
        os.replace(VERLAUF_DATEI + ".tmp", VERLAUF_DATEI)
    except OSError:
        pass


def verlauf_schleife():
    gesichert = time.time()
    while True:
        try:
            with urllib.request.urlopen(SENSOR, timeout=3) as r:
                d = json.loads(r.read())
            p = [round(time.time()), d.get("cpu"), prozessor_temp(d.get("temperaturen")), d.get("netz_rx"), d.get("netz_tx")]
            # kurze Logzeile alle 10 s (zum Nachsehen per Container-Log)
            if p[0] % 10 < 5:
                top = ", ".join(f'{x["name"]}@{x["gast"]} {x["cpu"]}%' for x in (d.get("prozesse") or [])[:4])
                print(f'{time.strftime("%H:%M:%S")} cpu {p[1]}% temp {p[2]} kerne {d.get("kerne_last")} | {top or "keine Programmliste (alter Messdienst)"}', flush=True)
            with SPERRE:
                KURZ.append(p)
                del KURZ[:-720]
                MINUTE.append(p)
                if p[0] // 60 != MINUTE[0][0] // 60:
                    alt = MINUTE[:-1]
                    del MINUTE[:-1]
                    if alt:
                        mittel = lambda i: round(sum(x[i] or 0 for x in alt) / len(alt), 1)
                        temps = [x[2] for x in alt if x[2] is not None]
                        LANG.append([alt[0][0] // 60 * 60, mittel(1), round(sum(temps) / len(temps), 1) if temps else None,
                                     round(mittel(3)), round(mittel(4)), max(temps) if temps else None])
                        del LANG[:-43200]
        except Exception:
            pass
        if time.time() - gesichert > 300:
            verlauf_sichern()
            gesichert = time.time()
        time.sleep(5)


def verlauf(bereich):
    jetzt = time.time()
    with SPERRE:
        if bereich == "1h":
            return {"punkte": list(KURZ), "schritt": 5}
        sek = {"6h": 6 * 3600, "24h": 86400, "7t": 7 * 86400, "30t": 30 * 86400}.get(bereich, 86400)
        daten = [x for x in LANG if x[0] >= jetzt - sek]
    # auf höchstens ~400 Punkte zusammenfassen (Mittel, Temperatur-Spitze bleibt erhalten)
    n = max(1, len(daten) // 400)
    erg = []
    for i in range(0, len(daten), n):
        g = daten[i:i + n]
        temps = [x[2] for x in g if x[2] is not None]
        spitzen = [x[5] for x in g if x[5] is not None]
        erg.append([g[0][0], round(sum(x[1] or 0 for x in g) / len(g), 1), round(sum(temps) / len(temps), 1) if temps else None,
                    round(sum(x[3] or 0 for x in g) / len(g)), round(sum(x[4] or 0 for x in g) / len(g)), max(spitzen) if spitzen else None])
    return {"punkte": erg, "schritt": 60 * n}


def werte():
    try:
        with urllib.request.urlopen(SENSOR, timeout=2) as r:
            d = json.loads(r.read())
        d["sensor"] = True
    except Exception as e:
        d = {"sensor": False, "fehler": str(e)}
    d["container"] = container()
    return d


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def senden(self, code, body, typ):
        self.send_response(code)
        self.send_header("Content-Type", typ)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if self.path.startswith("/api/netz/"):
            n = int(self.headers.get("Content-Length") or 0)
            return self.senden(*netz_weiter("POST", self.path, self.rfile.read(min(n, 10000))))
        if self.path.split("?")[0] == "/api/turbo":
            n = int(self.headers.get("Content-Length") or 0)
            try:
                an = bool(json.loads(self.rfile.read(min(n, 100)) or b"{}").get("an"))
            except ValueError:
                return self.senden(400, b'{"ok":false}', "application/json")
            code, body = turbo(an)
            return self.senden(code, body, "application/json")
        self.senden(404, b"nicht gefunden", "text/plain")

    def do_GET(self):
        pfad = self.path.split("?")[0]
        if pfad.startswith("/api/netz/"):
            return self.senden(*netz_weiter("GET", self.path))
        if pfad == "/api/verlauf":
            b = (self.path.split("bereich=")[1].split("&")[0] if "bereich=" in self.path else "1h")
            self.senden(200, json.dumps(verlauf(b)).encode(), "application/json")
        elif pfad == "/api/werte":
            self.senden(200, json.dumps(werte()).encode(), "application/json")
        elif pfad in ("/", "/index.html"):
            self.senden(200, lesen(HTML).encode(), "text/html; charset=utf-8")
        else:
            self.senden(404, b"nicht gefunden", "text/plain")


def turbo(an):
    req = urllib.request.Request(SENSOR.rsplit("/", 1)[0] + "/turbo", data=json.dumps({"an": an}).encode(),
                                 method="POST", headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return 200, r.read()
    except urllib.error.HTTPError as e:
        return e.code, json.dumps({"ok": False, "text": "Messdienst lehnt ab – bitte Messdienst aktualisieren"}).encode()
    except Exception as e:
        return 502, json.dumps({"ok": False, "text": "Messdienst nicht erreichbar"}).encode()


def netz_weiter(methode, pfad, daten=None):
    """Reicht /api/netz/* an die Netzwerk-App (ntopng + AdGuard) weiter."""
    req = urllib.request.Request(NETZ + "/api/" + pfad[len("/api/netz/"):], data=daten, method=methode,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, r.read(), r.headers.get("Content-Type") or "application/json"
    except urllib.error.HTTPError as e:
        return e.code, e.read(), "application/json"
    except Exception:
        return 502, b'{"ok":false,"fehler":"Netzwerk-App nicht erreichbar"}', "application/json"


class StillerServer(ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request, client_address):
        pass


if __name__ == "__main__":
    verlauf_laden()
    threading.Thread(target=verlauf_schleife, daemon=True).start()
    print(f"Pulswerk auf Port {PORT}, Messdienst {SENSOR}, Verlauf: {len(LANG)} Minuten", flush=True)
    StillerServer(("0.0.0.0", PORT), H).serve_forever()
