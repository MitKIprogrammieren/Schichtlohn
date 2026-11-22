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


# ---------- Plan: Heimnetz-Übersicht mit Live-Erreichbarkeit ----------
# Feste Beschreibung des Heimnetzes. Überschreibbar mit /daten/plan.json (gleiches Format).
# Feste Beschreibung des Heimnetzes (nur lokale Adressen). Private Adressen für unterwegs
# (Tailscale, Nabu Casa) kommen aus /plan.json bzw. /daten/plan.json und stehen nicht im Repo.
PLAN = {
    "geraete": [
        {
            "id": "fritz",
            "name": "FritzBox",
            "rolle": "Router · verteilt Adressen",
            "ip": "192.168.1.1",
            "ports": [
                80,
                443
            ],
            "art": "router",
            "url": "http://192.168.1.1"
        },
        {
            "id": "dscloud",
            "name": "DsCLoud",
            "rolle": "Synology DS718+ · Dateien & Backups",
            "ip": "192.168.1.4",
            "ports": [
                4001,
                5000,
                5001,
                443
            ],
            "art": "nas",
            "url": "https://192.168.1.4:4001"
        },
        {
            "id": "ds2",
            "name": "DS1819+",
            "rolle": "Synology · Filme & Serien",
            "ip": "192.168.1.2",
            "ports": [
                5000,
                5001,
                4001,
                443
            ],
            "art": "nas",
            "url": "http://192.168.1.2:5000"
        },
        {
            "id": "pve",
            "name": "NUC · Proxmox",
            "rolle": "Server für alle Werke",
            "ip": "192.168.1.5",
            "ports": [
                8006
            ],
            "art": "server",
            "url": "https://192.168.1.5:8006"
        },
        {
            "id": "ha",
            "name": "Home Assistant",
            "rolle": "Smart Home",
            "ip": "192.168.1.66",
            "ports": [
                8123
            ],
            "art": "ha",
            "url": "http://192.168.1.66:8123"
        },
        {
            "id": "usv",
            "name": "USV Zinto 1000",
            "rolle": "Notstrom",
            "ip": "192.168.1.3",
            "ports": [
                80,
                443,
                3493
            ],
            "art": "usv",
            "url": "http://192.168.1.3"
        },
        {
            "id": "pihole",
            "name": "Pi-hole",
            "rolle": "Raspberry Pi · abgeschaltet",
            "ip": "192.168.1.250",
            "ports": [
                80,
                53
            ],
            "art": "pi",
            "aus": True,
            "url": "http://192.168.1.250/admin"
        },
        {
            "id": "kind",
            "name": "Kinder-Gerät",
            "rolle": "sperrbar über Home Assistant",
            "ip": "192.168.1.31",
            "ports": [],
            "art": "handy"
        }
    ],
    "gaeste": {
        "100": {
            "rolle": "Docker · alle Werke",
            "ip": "192.168.1.30",
            "url": "http://192.168.1.30:8090"
        },
        "101": {
            "rolle": "AdGuard · Werbeblocker & DNS",
            "ip": "192.168.1.34",
            "url": "http://192.168.1.34"
        },
        "102": {
            "rolle": "JDownloader · Downloads",
            "ip": "192.168.1.37"
        },
        "103": {
            "rolle": "Plex · Filme & Serien",
            "ip": "192.168.1.21",
            "url": "http://192.168.1.21:32400/web"
        }
    },
    "werke_host": {
        "lokal": "192.168.1.30"
    },
    "unterwegs": []
}
PLAN_CACHE = {"zeit": 0, "daten": None}


def plan_laden():
    for pfad in ("/plan.json", os.path.join(DATEN, "plan.json")):
        try:
            with open(pfad) as f:
                return json.load(f)
        except (OSError, ValueError):
            continue
    return PLAN


def erreichbar(ip, ports):
    for p in ports:
        try:
            with socket.create_connection((ip, p), timeout=0.8):
                return True, p
        except OSError:
            continue
    return False, None


def docker_alle():
    try:
        c = UnixVerbindung()
        c.request("GET", "/containers/json?all=1")
        liste = json.loads(c.getresponse().read())
    except Exception:
        return []
    erg = []
    for x in liste:
        ports = sorted({p.get("PublicPort") or p.get("PrivatePort") for p in x.get("Ports") or [] if p.get("PublicPort") or p.get("PrivatePort")})
        erg.append({"name": x["Names"][0].lstrip("/"), "zustand": x.get("State"), "status": x.get("Status"),
                    "projekt": (x.get("Labels") or {}).get("com.docker.compose.project", ""), "ports": ports})
    return erg


# ---------- FritzBox-Geräteliste (TR-064): LAN/WLAN, Port, Tempo ----------
FBT = os.environ.get("FB_TR064", "http://192.168.1.1:49000").rstrip("/")
FB_ENV = os.environ.get("FB_ENV", "/fritz.env")
FRITZ = {"zeit": 0, "daten": None}


def fb_zugang():
    u, p = os.environ.get("FB_USER", ""), os.environ.get("FB_PASS", "")
    if u:
        return u, p
    for z in lesen(FB_ENV).splitlines():
        k, _, v = z.partition("=")
        if k.strip() == "FB_USER":
            u = v.strip()
        elif k.strip() == "FB_PASS":
            p = v.strip()
    return u, p


def soap(pfad, service, aktion, zugang):
    body = ('<?xml version="1.0"?><s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
            's:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/"><s:Body><u:' + aktion +
            ' xmlns:u="' + service + '"/></s:Body></s:Envelope>')
    mgr = urllib.request.HTTPPasswordMgrWithDefaultRealm()
    mgr.add_password(None, FBT, zugang[0], zugang[1])
    op = urllib.request.build_opener(urllib.request.HTTPDigestAuthHandler(mgr))
    req = urllib.request.Request(FBT + pfad, data=body.encode(), headers={
        "Content-Type": 'text/xml; charset="utf-8"', "SOAPAction": service + "#" + aktion})
    return op.open(req, timeout=10).read().decode("utf-8", "replace")


def fritz():
    import xml.etree.ElementTree as ET
    if FRITZ["daten"] and time.time() - FRITZ["zeit"] < 30:
        return FRITZ["daten"]
    zugang = fb_zugang()
    if not zugang[0]:
        return {"ok": False, "fehler": "Keine FritzBox-Zugangsdaten"}
    try:
        x = soap("/upnp/control/hosts", "urn:dslforum-org:service:Hosts:1", "X_AVM-DE_GetHostListPath", zugang)
        pfad = re.search(r"<NewX_AVM-DE_HostListPath>(.*?)</", x).group(1)
        with urllib.request.urlopen(FBT + pfad, timeout=10) as r:
            root = ET.fromstring(r.read())
    except Exception as e:
        d = {"ok": False, "fehler": "FritzBox-Geräteliste: " + str(e)}
        FRITZ.update(zeit=time.time() - 20, daten=d)
        return d
    namen = {}
    try:
        with urllib.request.urlopen(NETZ + "/api/stand", timeout=8) as r:
            namen = {g["ip"]: g["name"] for g in json.loads(r.read()).get("geraete", []) if g.get("name")}
    except Exception:
        pass
    geraete = []
    for item in root.iter("Item"):
        d = {k.tag: (k.text or "") for k in item}
        ip, typ = d.get("IPAddress", ""), d.get("InterfaceType", "")
        try:
            tempo = int(d.get("X_AVM-DE_Speed") or 0)
        except ValueError:
            tempo = 0
        geraete.append({"ip": ip, "mac": d.get("MACAddress", ""), "name": namen.get(ip) or d.get("HostName") or ip,
                        "fritzname": d.get("HostName", ""), "aktiv": d.get("Active") == "1",
                        "art": "wlan" if "802.11" in typ else "lan" if typ == "Ethernet" else "sonst",
                        "port": d.get("X_AVM-DE_Port", ""), "tempo": tempo, "gast": d.get("X_AVM-DE_Guest") == "1",
                        "modell": d.get("X_AVM-DE_Model", "")})
    wlan = []
    for i in range(1, 5):
        try:
            x = soap(f"/upnp/control/wlanconfig{i}", f"urn:dslforum-org:service:WLANConfiguration:{i}", "GetInfo", zugang)
            g = lambda k: (re.search(f"<New{k}>(.*?)</", x) or [None, ""])[1]
            wlan.append({"nr": i, "ssid": g("SSID"), "an": g("Enable") == "1", "kanal": g("Channel"),
                         "standard": g("Standard"), "band": g("X_AVM-DE_FrequencyBand")})
        except Exception:
            pass
    daten = {"ok": True, "zeit": int(time.time()), "geraete": geraete, "wlan": wlan}
    FRITZ.update(zeit=time.time(), daten=daten)
    return daten


def plan():
    if PLAN_CACHE["daten"] and time.time() - PLAN_CACHE["zeit"] < 15:
        return PLAN_CACHE["daten"]
    p = plan_laden()
    geraete = [dict(g) for g in p.get("geraete", [])]
    ergebnisse = {}

    def pruefen(g):
        if g.get("ports"):
            ergebnisse[g["id"]] = erreichbar(g["ip"], g["ports"])

    faeden = [threading.Thread(target=pruefen, args=(g,)) for g in geraete]
    for t in faeden:
        t.start()
    for t in faeden:
        t.join(4)
    for g in geraete:
        ok, port = ergebnisse.get(g["id"], (None, None))
        g["online"] = ok
        g["port"] = port
    try:
        with urllib.request.urlopen(SENSOR, timeout=2) as r:
            s = json.loads(r.read())
    except Exception:
        s = {}
    gaeste = []
    for x in s.get("gaeste") or []:
        info = p.get("gaeste", {}).get(str(x["id"]), {})
        gaeste.append({"id": x["id"], "name": x["name"], "ram": x.get("ram"), "cpu": x.get("cpu"), **info})
    daten = {"zeit": round(time.time()), "geraete": geraete, "gaeste": sorted(gaeste, key=lambda x: x["id"]),
             "container": docker_alle(), "unterwegs": p.get("unterwegs", []), "werke_host": p.get("werke_host", {}), "sensor": bool(s), "fritz": fritz()}
    PLAN_CACHE.update(zeit=time.time(), daten=daten)
    return daten


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
        elif pfad == "/api/plan":
            self.senden(200, json.dumps(plan()).encode(), "application/json")
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
