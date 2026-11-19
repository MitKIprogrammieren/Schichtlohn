"""Gridwerk – Gridfinity-Generator als Web-App (Proxmox-NUC).

Holt die Oberfläche aus dem Schichtlohn-Repo (gridwerk/index.html, über jsDelivr, fest auf den
neuesten Commit), speichert Listen/Einstellungen in /daten/liste.json und leitet QR-Kurzlinks
(/q/<code>) auf die hinterlegte Adresse weiter.
"""
import json, os, re, shutil, threading, time, urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

REPO = os.environ.get("REPO", "MitKIprogrammieren/Schichtlohn")
DATEI = "gridwerk/index.html"
PORT = int(os.environ.get("PORT", "8099"))
DATEN = os.environ.get("DATEN", "/daten")
CACHE = os.path.join(DATEN, "gridwerk.html")
LISTE = os.path.join(DATEN, "liste.json")
ALT = os.path.join(os.environ.get("ALT", "/alt"), "liste.json")  # Liste aus der Vorgängerversion (Rasterwerk) einmalig übernehmen
STAND = {"html": None, "sha": "", "zeit": 0}


def holen(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": "gridwerk-nuc", "Accept": "application/vnd.github.sha"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def aktualisieren():
    try:
        sha = holen(f"https://api.github.com/repos/{REPO}/commits/main").decode().strip()
        if not re.fullmatch(r"[0-9a-f]{40}", sha):
            sha = "main"
    except Exception:
        sha = "main"
    if sha != "main" and sha == STAND["sha"] and STAND["html"]:
        return
    try:
        html = holen(f"https://cdn.jsdelivr.net/gh/{REPO}@{sha}/{DATEI}", 30)
        if b"Gridwerk" not in html:
            raise ValueError("unerwarteter Inhalt")
        STAND.update(html=html, sha=sha, zeit=time.time())
        try:
            with open(CACHE, "wb") as f:
                f.write(html)
        except OSError:
            pass
        print(f"Gridwerk-Stand {sha[:7]} geladen ({len(html)} Bytes)", flush=True)
    except Exception as e:
        print("Aktualisieren fehlgeschlagen:", e, flush=True)


def schleife():
    while True:
        aktualisieren()
        time.sleep(600)


def kurzlink(code):
    try:
        with open(LISTE, encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError):
        return None
    for e in d.get("liste", []):
        if e.get("qrKurz") and str(e.get("qrCode", "")).lower() == code.lower():
            ziel = str(e.get("qr", "")).strip()
            if re.match(r"^https?://", ziel, re.I):
                return ziel
    return None


class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def senden(self, code, body, typ="application/json; charset=utf-8", kopf=None):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", typ)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (kopf or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        p = self.path.split("?")[0]
        pl = p.lower()
        if pl in ("/", "/index.html"):
            if not STAND["html"]:
                return self.senden(503, "Gridwerk wird geladen – gleich neu laden.", "text/plain; charset=utf-8")
            return self.senden(200, STAND["html"], "text/html; charset=utf-8")
        if pl == "/gesund":
            return self.senden(200 if STAND["html"] else 503, json.dumps({"ok": bool(STAND["html"]), "stand": STAND["sha"][:7]}))
        if pl == "/api/liste":
            try:
                with open(LISTE, "rb") as f:
                    return self.senden(200, f.read())
            except OSError:
                return self.senden(200, "{}")
        m = re.fullmatch(r"/q/([a-z0-9]{1,12})", pl)
        if m:
            ziel = kurzlink(m.group(1))
            if ziel:
                return self.senden(302, "", "text/plain", {"Location": ziel})
            return self.senden(404, "Kurzlink unbekannt", "text/plain; charset=utf-8")
        self.senden(404, '{"ok":false}')

    def do_PUT(self):
        if self.path.split("?")[0] != "/api/liste":
            return self.senden(404, '{"ok":false}')
        n = int(self.headers.get("Content-Length") or 0)
        if n > 16 * 1024 * 1024:
            return self.senden(413, '{"ok":false,"text":"zu groß"}')
        daten = self.rfile.read(n)
        try:
            json.loads(daten)
        except ValueError:
            return self.senden(400, '{"ok":false}')
        tmp = LISTE + ".tmp"
        with open(tmp, "wb") as f:
            f.write(daten)
        os.replace(tmp, LISTE)
        self.senden(200, '{"ok":true}')


if __name__ == "__main__":
    os.makedirs(DATEN, exist_ok=True)
    if not os.path.exists(LISTE) and os.path.exists(ALT):
        shutil.copyfile(ALT, LISTE)
        print("Liste aus Rasterwerk übernommen", flush=True)
    try:
        with open(CACHE, "rb") as f:
            STAND["html"] = f.read()
            print("Zwischenstand aus", CACHE, flush=True)
    except OSError:
        pass
    threading.Thread(target=schleife, daemon=True).start()
    print(f"Gridwerk läuft auf Port {PORT}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), H).serve_forever()
