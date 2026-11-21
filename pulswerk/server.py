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
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = int(os.environ.get("PORT", "8088"))
SENSOR = os.environ.get("SENSOR", "http://192.168.1.5:9105/werte")
HTML = os.environ.get("HTML", os.path.join(os.path.dirname(os.path.abspath(__file__)), "index.html"))
CG = os.environ.get("CG", "/cg")
SOCK = "/var/run/docker.sock"
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

    def do_GET(self):
        pfad = self.path.split("?")[0]
        if pfad == "/api/werte":
            self.senden(200, json.dumps(werte()).encode(), "application/json")
        elif pfad in ("/", "/index.html"):
            self.senden(200, lesen(HTML).encode(), "text/html; charset=utf-8")
        else:
            self.senden(404, b"nicht gefunden", "text/plain")


class StillerServer(ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request, client_address):
        pass


if __name__ == "__main__":
    print(f"Pulswerk auf Port {PORT}, Messdienst {SENSOR}", flush=True)
    StillerServer(("0.0.0.0", PORT), H).serve_forever()
