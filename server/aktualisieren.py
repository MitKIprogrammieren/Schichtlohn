"""Selbst-Update des SchichtLohn-Servers im Docker-Container (z. B. auf dem Proxmox-NUC).

Voraussetzung: der Docker-Socket ist in den Container eingebunden (- /var/run/docker.sock:/var/run/docker.sock).
Ablauf:
  1. pruefen()  – läuft der Server in Docker und ist der Socket da?
  2. starten()  – neues Image holen; ist es neuer, startet ein kurzer Helfer-Container aus dem NEUEN Image
                  mit „python aktualisieren.py ersetzen <alter Container>“ und meldet sich ab.
  3. ersetzen() – (im Helfer) alten Container anhalten, mit gleichen Einstellungen neu anlegen und starten,
                  danach den alten löschen. Geht etwas schief, läuft der alte Container wieder an.
Nur Python-Standardbibliothek; Docker-Schnittstelle direkt über den Unix-Socket.
"""
import http.client
import json
import os
import socket
import sys
import time
import urllib.parse

SOCK = "/var/run/docker.sock"


class _Verbindung(http.client.HTTPConnection):
    def __init__(self, timeout=600):
        super().__init__("localhost", timeout=timeout)

    def connect(self):
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(self.timeout)
        s.connect(SOCK)
        self.sock = s


def _docker(methode, pfad, rumpf=None, timeout=600):
    c = _Verbindung(timeout)
    kopf = {"Content-Type": "application/json"} if rumpf is not None else {}
    c.request(methode, pfad, body=json.dumps(rumpf) if rumpf is not None else None, headers=kopf)
    r = c.getresponse()
    daten = r.read()
    c.close()
    if r.status >= 400:
        try:
            msg = json.loads(daten.decode("utf-8")).get("message")
        except Exception:
            msg = daten[:200].decode("utf-8", "replace")
        raise RuntimeError(f"Docker {r.status}: {msg}")
    if not daten:
        return None
    try:
        return json.loads(daten.decode("utf-8"))
    except ValueError:
        return daten.decode("utf-8", "replace")  # z. B. Fortschritt beim Image-Holen


def _selbst():
    """Eigener Container (Hostname = kurze Container-ID)."""
    return _docker("GET", "/containers/%s/json" % socket.gethostname(), timeout=15)


def pruefen():
    if not os.path.exists(SOCK):
        return {"moeglich": False, "grund": "kein Docker-Socket eingebunden"}
    try:
        s = _selbst()
        return {"moeglich": True, "container": s["Name"].lstrip("/"), "image": s["Config"]["Image"]}
    except Exception as e:
        return {"moeglich": False, "grund": str(e)[:200]}


def starten():
    s = _selbst()
    bild = s["Config"]["Image"]
    name, _, tag = bild.rpartition(":") if ":" in bild.split("/")[-1] else (bild, "", "latest")
    antwort = _docker("POST", "/images/create?" + urllib.parse.urlencode({"fromImage": name, "tag": tag or "latest"}))
    for zeile in str(antwort or "").splitlines():
        if '"error"' in zeile:
            raise RuntimeError("Image holen: " + (json.loads(zeile).get("error") or zeile)[:200])
    neu = _docker("GET", "/images/%s/json" % urllib.parse.quote(bild, safe=""), timeout=30)
    if neu["Id"] == s["Image"]:
        return {"ok": True, "neu": False}
    helfer = _docker("POST", "/containers/create?" + urllib.parse.urlencode({"name": "schichtlohn-update-%d" % int(time.time())}), {
        "Image": bild, "Cmd": ["python", "aktualisieren.py", "ersetzen", s["Id"]],
        "Env": ["PYTHONUNBUFFERED=1"],
        "HostConfig": {"Binds": ["%s:%s" % (SOCK, SOCK)], "AutoRemove": True},
        "Labels": {"schichtlohn.helfer": "update"}}, timeout=30)
    _docker("POST", "/containers/%s/start" % helfer["Id"], timeout=30)
    return {"ok": True, "neu": True}


def ersetzen(alt_id):
    time.sleep(2)  # Antwort an die App noch durchlassen
    alt = _docker("GET", "/containers/%s/json" % alt_id, timeout=15)
    name = alt["Name"].lstrip("/")
    cfg = dict(alt["Config"])
    for k in ("Hostname", "Domainname"):  # neuer Container bekommt eigene ID als Hostnamen
        cfg.pop(k, None)
    hc = alt["HostConfig"]
    netze = {n: {"Aliases": [a for a in (v.get("Aliases") or []) if a != alt_id[:12]]}
             for n, v in (alt.get("NetworkSettings") or {}).get("Networks", {}).items()}
    cfg["HostConfig"] = hc
    cfg["NetworkingConfig"] = {"EndpointsConfig": netze}
    print("Halte", name, "an …", flush=True)
    _docker("POST", "/containers/%s/stop?t=15" % alt_id, timeout=60)
    _docker("POST", "/containers/%s/rename?name=%s" % (alt_id, urllib.parse.quote(name + "-alt")), timeout=15)
    try:
        neu = _docker("POST", "/containers/create?name=%s" % urllib.parse.quote(name), cfg, timeout=60)
        _docker("POST", "/containers/%s/start" % neu["Id"], timeout=60)
    except Exception as e:
        print("Neuer Container ging nicht:", e, "– alter läuft wieder an", flush=True)
        try:
            _docker("DELETE", "/containers/%s?force=1" % urllib.parse.quote(name), timeout=30)
        except Exception:
            pass
        _docker("POST", "/containers/%s/rename?name=%s" % (alt_id, urllib.parse.quote(name)), timeout=15)
        _docker("POST", "/containers/%s/start" % alt_id, timeout=60)
        return
    _docker("DELETE", "/containers/%s?force=1" % alt_id, timeout=60)
    try:  # altes Image aufräumen, wenn es nicht mehr gebraucht wird
        _docker("DELETE", "/images/%s" % alt["Image"], timeout=60)
    except Exception:
        pass
    print("Fertig:", name, "läuft mit dem neuen Image", flush=True)


if __name__ == "__main__" and len(sys.argv) > 2 and sys.argv[1] == "ersetzen":
    ersetzen(sys.argv[2])
