"""SchichtLohn-App direkt von der Synology ausliefern – auch ohne Internet.

  GET  /app/                 die App (index.html), CDN-Adressen auf diesen Server umgeschrieben
  GET  /app/<datei>          Manifest und Icons
  GET  /npm/…  /cdnjs/…      Bibliotheken (Barcode-Leser, PDF, ZIP, QR) – beim ersten Abruf aus dem
  GET  /gfonts/… /gstatic/…  Internet geholt und auf der Synology gespeichert, danach offline

Eine Grundversion der App steckt im Container; „App aktualisieren“ holt die neueste Fassung
von GitHub Pages nach /daten/app und lädt alle Bibliotheken vorab in den Zwischenspeicher.
"""
import hashlib
import json
import os
import re
import time
import urllib.request

APP_URL = os.environ.get("APP_URL", "https://mitkiprogrammieren.github.io/Schichtlohn/")
APP_DATEIEN = ["index.html", "manifest.webmanifest", "icon.svg", "icon-180.png", "icon-192.png", "icon-512.png", "scan.html"]
UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 "
      "(KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1")

QUELLEN = {
    "npm": "https://cdn.jsdelivr.net/npm/",
    "cdnjs": "https://cdnjs.cloudflare.com/ajax/libs/",
    "gfonts": "https://fonts.googleapis.com/",
    "gstatic": "https://fonts.gstatic.com/",
}
UMSCHREIBEN = [
    ("https://cdn.jsdelivr.net/npm/", "/npm/"),
    ("https://cdnjs.cloudflare.com/ajax/libs/", "/cdnjs/"),
    ("https://fonts.googleapis.com/", "/gfonts/"),
    ("https://fonts.gstatic.com/", "/gstatic/"),
]
TYPEN = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".mjs": "text/javascript; charset=utf-8",
         ".css": "text/css; charset=utf-8", ".svg": "image/svg+xml", ".png": "image/png", ".json": "application/json",
         ".webmanifest": "application/manifest+json", ".woff2": "font/woff2", ".woff": "font/woff", ".ttf": "font/ttf"}


class Ordner:
    def __init__(self, daten):
        self.app = os.path.join(daten, "app")
        self.vendor = os.path.join(daten, "vendor")
        self.eingebaut = os.environ.get("APP_EINGEBAUT", "/app/modelle/web")
        self.vendor_eingebaut = os.environ.get("VENDOR_EINGEBAUT", "/app/modelle/vendor")


def typ_fuer(name, standard="application/octet-stream"):
    n = name.split("?")[0].lower()
    if n.endswith("+esm") or "/+esm" in n:
        return "text/javascript; charset=utf-8"
    for endung, t in TYPEN.items():
        if n.endswith(endung):
            return t
    return standard


def umschreiben(text):
    for alt, neu in UMSCHREIBEN:
        text = text.replace(alt, neu)
    return text


def app_datei(o, name):
    """Pfad der App-Datei: neueste Fassung auf der Synology, sonst die im Container."""
    if name not in APP_DATEIEN:
        return None
    for basis in (o.app, o.eingebaut):
        p = os.path.join(basis, name)
        if os.path.exists(p):
            return p
    return None


def app_html(o, basis=""):
    p = app_datei(o, "index.html")
    if not p:
        return None
    with open(p, encoding="utf-8") as f:
        html = f.read()
    html = umschreiben(html)
    if basis:  # Home Assistant (Ingress): alles liegt unter /api/hassio_ingress/<schlüssel>
        for _, neu in UMSCHREIBEN:
            html = html.replace('"' + neu, '"' + basis + neu).replace("'" + neu, "'" + basis + neu).replace("`" + neu, "`" + basis + neu)
    # Kennzeichen für die App: läuft vom SchichtLohn-Server (Server-Adresse = diese Seite)
    return html.replace("<head>", "<head><script>window.__SL_SRV=1;window.__SL_BASE=%s</script>" % json.dumps(basis), 1)


def app_info(o):
    p = app_datei(o, "index.html")
    if not p:
        return {"vorhanden": False}
    st = time.strftime("%Y-%m-%d %H:%M", time.localtime(os.path.getmtime(p)))
    n = 0
    if os.path.isdir(o.vendor):
        for _, _, fs in os.walk(o.vendor):
            n += sum(1 for f in fs if not f.endswith(".typ"))
    return {"vorhanden": True, "stand": st, "quelle": "auf dem Server gespeichert" if p.startswith(o.app) else "im Container mitgeliefert",
            "bibliotheken": n}


# ------------------------------------------------------------ Zwischenspeicher für Bibliotheken

def _cache_pfad(o, art, rest):
    h = hashlib.sha1(rest.encode("utf-8")).hexdigest()
    return os.path.join(o.vendor, art, h[:2], h)


def holen(url, timeout=30):
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=timeout) as r:
        return r.read(), r.headers.get("Content-Type") or ""


def vendor(o, art, rest, online=True):
    """→ (body, content_type) aus dem Zwischenspeicher, sonst aus dem Internet (und speichern)."""
    if art not in QUELLEN:
        return None
    p = _cache_pfad(o, art, rest)
    if not os.path.exists(p):
        q = os.path.join(o.vendor_eingebaut, os.path.relpath(p, o.vendor))
        if os.path.exists(q):
            p = q
    if os.path.exists(p):
        with open(p, "rb") as f:
            body = f.read()
        try:
            with open(p + ".typ", encoding="utf-8") as f:
                typ = f.read().strip()
        except OSError:
            typ = typ_fuer(rest)
        return body, typ
    if not online:
        return None
    body, typ = holen(QUELLEN[art] + rest)
    typ = typ or typ_fuer(rest)
    if any(t in typ for t in ("javascript", "css", "json")) or rest.endswith("+esm"):
        body = umschreiben(body.decode("utf-8")).encode("utf-8")
    p = _cache_pfad(o, art, rest)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".neu"
    with open(tmp, "wb") as f:
        f.write(body)
    os.replace(tmp, p)
    with open(p + ".typ", "w", encoding="utf-8") as f:
        f.write(typ)
    return body, typ


_ADRESSE = re.compile(r"""(?:https://(?:cdn\.jsdelivr\.net/npm|cdnjs\.cloudflare\.com/ajax/libs|fonts\.googleapis\.com|fonts\.gstatic\.com)/|(?<=["'(])/(?:npm|cdnjs|gfonts|gstatic)/)[^"'`)\s${}]+""")


def _adressen(text):
    out = []
    for m in _ADRESSE.finditer(text):
        u = umschreiben(m.group(0))
        if "${" in u or u.endswith("/"):
            continue
        art, _, rest = u.lstrip("/").partition("/")
        if art in QUELLEN and rest:
            out.append((art, rest.replace("&amp;", "&")))
    return out


def vorladen(o, html):
    """Alle Bibliotheken der App in den Zwischenspeicher – samt der Dateien, die sie selbst nachladen."""
    offen, fertig, fehler = _adressen(html), set(), []
    while offen and len(fertig) < 200:
        art, rest = offen.pop()
        if (art, rest) in fertig:
            continue
        fertig.add((art, rest))
        try:
            body, typ = vendor(o, art, rest)
        except Exception as e:
            fehler.append(f"{art}/{rest}: {e}")
            continue
        if any(t in typ for t in ("javascript", "css")):
            offen.extend(_adressen(body.decode("utf-8", "replace")))
    return len(fertig) - len(fehler), fehler


def aktualisieren(o):
    """Neueste App von GitHub Pages holen, Bibliotheken vorladen."""
    os.makedirs(o.app, exist_ok=True)
    neu = {}
    for name in APP_DATEIEN:
        try:
            body, _ = holen(APP_URL + name + ("?t=%d" % time.time()), timeout=60)
        except Exception as e:
            if name == "index.html":
                raise RuntimeError("Download fehlgeschlagen (Internet an der Synology?): " + str(e))
            continue
        neu[name] = body
    if b"SchichtLohn" not in neu.get("index.html", b"") or len(neu["index.html"]) < 100000:
        raise RuntimeError("Die geladene App ist unvollständig, die bisherige bleibt erhalten")
    for name, body in neu.items():
        tmp = os.path.join(o.app, name + ".neu")
        with open(tmp, "wb") as f:
            f.write(body)
        os.replace(tmp, os.path.join(o.app, name))
    n, fehler = vorladen(o, neu["index.html"].decode("utf-8"))
    info = app_info(o)
    info.update({"geladen": n, "fehler": fehler[:5]})
    return info


if __name__ == "__main__":
    # Beim Bauen des Containers: App und Bibliotheken mitliefern
    import sys
    ziel = sys.argv[1] if len(sys.argv) > 1 else "/modelle"
    o = Ordner(ziel)
    o.app = os.path.join(ziel, "web")
    o.vendor = os.path.join(ziel, "vendor")
    try:
        info = aktualisieren(o)
        print("App mitgeliefert:", info)
    except Exception as e:
        print("App nicht mitgeliefert:", e)
