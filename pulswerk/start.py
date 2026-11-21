"""Startet das Pulswerk: holt server.py und index.html aus dem Schichtlohn-Repo (jsDelivr,
fest auf den neuesten Commit von main) und startet dann den Server. Ohne Internet läuft der
zuletzt geladene Stand aus /daten/.code weiter."""
import os, re, sys, urllib.request

REPO = os.environ.get("REPO", "MitKIprogrammieren/Schichtlohn")
ZIEL = os.path.join(os.environ.get("DATEN", "/daten"), ".code")
DATEIEN = ("server.py", "index.html")


def holen(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": "pulswerk-nuc", "Accept": "application/vnd.github.sha"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def laden():
    sha = holen(f"https://api.github.com/repos/{REPO}/commits/main").decode().strip()
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise ValueError("kein Commit-Stand")
    neu = {d: holen(f"https://cdn.jsdelivr.net/gh/{REPO}@{sha}/pulswerk/{d}") for d in DATEIEN}
    if b"def main" not in neu["server.py"] and b"__main__" not in neu["server.py"]:
        raise ValueError("server.py unerwartet")
    if b"Pulswerk" not in neu["index.html"]:
        raise ValueError("index.html unerwartet")
    os.makedirs(ZIEL, exist_ok=True)
    for d, inhalt in neu.items():
        with open(os.path.join(ZIEL, d + ".tmp"), "wb") as f:
            f.write(inhalt)
        os.replace(os.path.join(ZIEL, d + ".tmp"), os.path.join(ZIEL, d))
    with open(os.path.join(ZIEL, "STAND"), "w") as f:
        f.write(sha)
    print(f"Pulswerk-Stand {sha[:7]} geladen", flush=True)


try:
    laden()
except Exception as e:
    print("Laden aus GitHub fehlgeschlagen, nutze letzten Stand:", e, flush=True)

server = os.path.join(ZIEL, "server.py")
if not os.path.exists(server):
    sys.exit("Noch kein Code vorhanden – Internet prüfen.")
os.environ["HTML"] = os.path.join(ZIEL, "index.html")
os.execv(sys.executable, [sys.executable, "-u", server])
