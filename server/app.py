#!/usr/bin/env python3
"""SchichtLohn-Server für die Synology.

Eine Datenbank (SQLite) für das Lager und die SchichtLohn-Daten, damit alle Geräte
(Mac, iPhone, Home Assistant, Waage) denselben Stand haben. Dazu der Etikett-Leser
(Text und Barcodes von Spulenfotos, läuft lokal).

Listen haben dasselbe Format wie die To-do-Listen in Home Assistant
(uid, summary, status, description), damit das Lager unverändert weiterarbeitet.

  GET  /                              Status
  GET  /api/listen/<name>             Einträge einer Liste (z. B. todo.filament)
  POST /api/listen/<name>             {"service": "add_item"|"update_item"|"remove_item", "data": {...}}
  PUT  /api/listen/<name>             {"items": [...]}  ganze Liste ersetzen (Übernahme)
  GET  /api/daten/<schlüssel>         gespeicherter Wert (cfg, portfolio, orders …)
  PUT  /api/daten/<schlüssel>         {"wert": ...}
  GET  /api/ereignisse                Live-Meldungen bei Änderungen (Server-Sent Events)
  GET  /api/sorten                    Lager vereinfacht (für die Waage)
  GET  /api/sicherung                 alles als JSON (Backup)
  POST /lesen                         Rumpf = Bild; Etikett-Text und Barcodes
  GET  /app/                          die SchichtLohn-App (läuft so auch ohne Internet), /npm/ … Bibliotheken
  GET  /api/einstellungen, PUT        Drucker, Bambu-Cloud, Home Assistant (Schlüssel maskiert)
  POST /api/telegram/chat, …/test     Telegram-Bot: Chat-ID finden, Testmeldung
  POST /api/waage/drucken             Etikett (1-Bit-Raster) an die Filamentwaage weiterreichen
  POST /api/werte_ergaenzen           leere Druckwerte (Düse, Bett, Flow, K, Vol.) aus Slicerprofilen ergänzen
  GET  /api/waage/drucker             Etikettendrucker, die die Waage in Home Assistant hat (M20 Pro, M110 …)
  GET  /api/preise, POST …/abrufen    Preisvergleich eBay/AliExpress je Sorte (Schlüssel unter Einstellungen)
  GET  /api/preise/protokoll          die letzten Preisabrufe: Zeit, Anlass, Dauer, Ergebnis je Sorte
  GET  /api/preise/suche?q=…          freie Suche bei eBay und AliExpress (Preisvergleichsseite)
  GET  /api/drucker                   verbundene Bambu-Drucker (MQTT) mit AMS-Fächern
  GET  /api/faecher                   alle AMS-Fächer mit Prüfung gegen das Lager (zugeordnet / offen)

Wie Home Assistant (damit Waage und Lager-Ansicht unverändert arbeiten):
  POST /api/services/todo/get_items|update_item|add_item|remove_item
  GET/POST /api/states[/<entity>]     Drucker, AMS, Feuchte, Waage
  POST /api/template                  AMS-Vorlage der Waage (sonst an HA weitergereicht)
  POST /api/events/<name>             an HA weitergereicht, falls eingetragen

Mit der Umgebungsvariable TOKEN verlangt der Server bei /api/* den Schlüssel
(Kopfzeile X-Token oder ?token=…). Ohne TOKEN ist alles im Heimnetz offen.
"""
import io
import hashlib
import json
import os
import re
import queue
import sqlite3
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, quote, unquote, urlparse

import drucker as drucker_mod
import preise as preise_mod
import mcp as mcp_mod
import produktbilder
import web

# Als Home-Assistant-App: Optionen aus /data/options.json übernehmen
try:
    with open("/data/options.json", encoding="utf-8") as _f:
        _opt = json.load(_f)
    if _opt.get("lesemodell") and _opt["lesemodell"] != "auto":
        os.environ.setdefault("LESEMODELL", str(_opt["lesemodell"]))
    if _opt.get("token"):
        os.environ.setdefault("TOKEN", str(_opt["token"]))
except (OSError, ValueError):
    pass
HA_APP = bool(os.environ.get("SUPERVISOR_TOKEN"))

VERSION = "3.8.2"
PORT = int(os.environ.get("PORT", "8093"))
DB_PFAD = os.environ.get("DB", "/daten/schichtlohn.db")
TOKEN_UMGEBUNG = os.environ.get("TOKEN", "").strip()  # aus der HA-Konfiguration (token) bzw. docker-compose (TOKEN=…)
ZUGANG_KEY = "_zugang"   # in der App gesetzter Schlüssel, falls keiner aus der Umgebung kommt
_zugang_cache = {"t": None}


def token_aktuell():
    """Gültiger App-Schlüssel: der aus der Umgebung hat Vorrang, sonst der in der App gesetzte, sonst keiner."""
    if TOKEN_UMGEBUNG:
        return TOKEN_UMGEBUNG
    if _zugang_cache["t"] is None:
        try:
            w, _ = daten_lesen(ZUGANG_KEY)
        except Exception:
            w = None
        _zugang_cache["t"] = str((w or {}).get("token") or "") if isinstance(w, dict) else ""
    return _zugang_cache["t"]


def zugang_setzen(token):
    if token:
        daten_schreiben(ZUGANG_KEY, {"token": token, "seit": time.strftime("%Y-%m-%dT%H:%M:%S")}, "zugang")
    else:
        daten_schreiben(ZUGANG_KEY, {"token": "", "seit": time.strftime("%Y-%m-%dT%H:%M:%S")}, "zugang")
    _zugang_cache["t"] = token or ""


def zugang_erzeugen():
    import secrets
    abc = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz23456789"  # ohne leicht verwechselbare Zeichen
    return "-".join("".join(secrets.choice(abc) for _ in range(4)) for _ in range(4))
MAX_BILD = 15 * 1024 * 1024
MAX_JSON = 32 * 1024 * 1024
MAX_SEITE = int(os.environ.get("MAX_SEITE", "1600"))
OCR_AN = os.environ.get("OCR", "1") != "0"
MERKMAL_MODELL = os.environ.get("MERKMAL_MODELL", "/app/modelle/mnv2_merkmale.onnx")
MODELLE = os.environ.get("MODELLE", os.path.dirname(MERKMAL_MODELL))

# ---------------------------------------------------------------- Datenbank

_db_lock = threading.RLock()  # auch Lesen sperren: eine gemeinsame Verbindung für alle Threads


def db():
    if not hasattr(db, "con"):
        os.makedirs(os.path.dirname(os.path.abspath(DB_PFAD)), exist_ok=True)
        con = sqlite3.connect(DB_PFAD, check_same_thread=False, isolation_level=None)
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA synchronous=NORMAL")
        con.executescript("""
            CREATE TABLE IF NOT EXISTS eintraege(
              liste TEXT NOT NULL, uid TEXT NOT NULL, summary TEXT NOT NULL DEFAULT '',
              status TEXT NOT NULL DEFAULT 'needs_action', description TEXT NOT NULL DEFAULT '',
              pos INTEGER NOT NULL DEFAULT 0, geaendert REAL NOT NULL,
              PRIMARY KEY(liste, uid));
            CREATE TABLE IF NOT EXISTS daten(
              schluessel TEXT PRIMARY KEY, wert TEXT NOT NULL, geaendert REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS stand(name TEXT PRIMARY KEY, rev INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS abdruecke(id INTEGER PRIMARY KEY AUTOINCREMENT, uid TEXT NOT NULL, vek BLOB NOT NULL, zeit REAL NOT NULL);
            CREATE INDEX IF NOT EXISTS abdruecke_uid ON abdruecke(uid);
        """)
        db.con = con
    return db.con


def rev(name, erhoehen=False):
    con = db()
    if erhoehen:
        con.execute("INSERT INTO stand(name, rev) VALUES(?, 1) ON CONFLICT(name) DO UPDATE SET rev = rev + 1", (name,))
    r = con.execute("SELECT rev FROM stand WHERE name=?", (name,)).fetchone()
    return r[0] if r else 0


def liste_lesen(name):
    rows = db().execute("SELECT uid, summary, status, description FROM eintraege WHERE liste=? ORDER BY pos, rowid", (name,)).fetchall()
    return [{"uid": u, "summary": s, "status": st, "description": d} for u, s, st, d in rows]


def liste_aendern(name, service, data):
    con = db()
    jetzt = time.time()
    with _db_lock:
        con.execute("BEGIN IMMEDIATE")
        try:
            if service == "add_item":
                pos = (con.execute("SELECT COALESCE(MAX(pos), 0) FROM eintraege WHERE liste=?", (name,)).fetchone()[0] or 0) + 1
                uid = str(data.get("uid") or uuid.uuid4())
                con.execute("INSERT INTO eintraege(liste, uid, summary, status, description, pos, geaendert) VALUES(?,?,?,?,?,?,?)",
                            (name, uid, str(data.get("item") or ""), str(data.get("status") or "needs_action"),
                             str(data.get("description") or ""), pos, jetzt))
                ergebnis = {"uid": uid}
            elif service == "update_item":
                item = str(data.get("item") or "")
                r = con.execute("SELECT uid FROM eintraege WHERE liste=? AND uid=?", (name, item)).fetchone() or \
                    con.execute("SELECT uid FROM eintraege WHERE liste=? AND summary=? ORDER BY pos LIMIT 1", (name, item)).fetchone()
                if not r:
                    raise KeyError("Eintrag nicht gefunden")
                felder, werte = [], []
                for k, spalte in (("rename", "summary"), ("description", "description"), ("status", "status")):
                    if data.get(k) is not None:
                        felder.append(spalte + "=?")
                        werte.append(str(data[k]))
                felder.append("geaendert=?")
                werte.append(jetzt)
                con.execute(f"UPDATE eintraege SET {', '.join(felder)} WHERE liste=? AND uid=?", (*werte, name, r[0]))
                ergebnis = {"uid": r[0]}
            elif service == "remove_item":
                ids = data.get("item")
                ids = ids if isinstance(ids, list) else [ids]
                n = 0
                for i in ids:
                    n += con.execute("DELETE FROM eintraege WHERE liste=? AND (uid=? OR summary=?)", (name, str(i), str(i))).rowcount
                ergebnis = {"entfernt": n}
            else:
                raise ValueError("Nicht unterstützt: " + str(service))
            r = rev(name, True)
            con.execute("COMMIT")
        except Exception:
            con.execute("ROLLBACK")
            raise
    melden({"typ": "liste", "name": name, "rev": r})
    ergebnis["rev"] = r
    return ergebnis


def liste_ersetzen(name, items):
    con = db()
    jetzt = time.time()
    with _db_lock:
        con.execute("BEGIN IMMEDIATE")
        try:
            con.execute("DELETE FROM eintraege WHERE liste=?", (name,))
            for pos, it in enumerate(items, 1):
                con.execute("INSERT OR REPLACE INTO eintraege(liste, uid, summary, status, description, pos, geaendert) VALUES(?,?,?,?,?,?,?)",
                            (name, str(it.get("uid") or uuid.uuid4()), str(it.get("summary") or ""),
                             str(it.get("status") or "needs_action"), str(it.get("description") or ""), pos, jetzt))
            r = rev(name, True)
            con.execute("COMMIT")
        except Exception:
            con.execute("ROLLBACK")
            raise
    melden({"typ": "liste", "name": name, "rev": r})
    return {"anzahl": len(items), "rev": r}


def daten_lesen(k):
    with _db_lock:
        r = db().execute("SELECT wert, geaendert FROM daten WHERE schluessel=?", (k,)).fetchone()
    if r and r[0] is None:
        raise RuntimeError(f"Daten „{k}“ nicht lesbar")
    return (json.loads(r[0]), r[1]) if r else (None, None)


def daten_schreiben(k, wert, quelle=""):
    with _db_lock:
        db().execute("INSERT INTO daten(schluessel, wert, geaendert) VALUES(?,?,?) ON CONFLICT(schluessel) DO UPDATE SET wert=excluded.wert, geaendert=excluded.geaendert",
                     (k, json.dumps(wert, ensure_ascii=False), time.time()))
        r = rev("daten:" + k, True)
    melden({"typ": "daten", "name": k, "rev": r, "quelle": quelle})
    return r


def sorten():
    out = []
    for it in liste_lesen("todo.filament"):
        try:
            d = json.loads(it["description"] or "{}")
        except ValueError:
            continue
        if not isinstance(d, dict) or not d.get("material"):
            continue
        out.append({"uid": it["uid"], "name": it["summary"], "hersteller": d.get("hersteller"), "material": d.get("material"),
                    "farbe": d.get("farbe"), "hex": d.get("hex"), "besonderheiten": d.get("besonderheiten") or [],
                    "gewicht": d.get("gewicht"), "spulen": d.get("spulen"), "reste": d.get("reste") or [],
                    "codes": d.get("codes") or [], "bambu_id": d.get("bambu_id") or ""})
    return out


# ---------------------------------------------------------------- Filament-Datenbank (Open Filament Database + SpoolmanDB)
# Liegt als Datei auf der Synology, damit die Suche auch ohne Internet funktioniert.
# Eine Grundversion steckt im Container; „Aktualisieren“ holt die wöchentlich gebaute neue Fassung.

HERSTELLER_ORDNER = ["/homeassistant/www/hersteller", "/config/www/hersteller",
                     os.path.join(os.path.dirname(os.path.abspath(DB_PFAD)), "hersteller")]
FDB_URL = os.environ.get("FDB_URL", "")  # leer = über jsDelivr, neuester Stand
FDB_DATEI = os.path.join(os.path.dirname(os.path.abspath(DB_PFAD)), "filamentdb.json")
FDB_EINGEBAUT = "/app/modelle/filamentdb.json"


def fdb_pfad():
    if os.path.exists(FDB_DATEI):
        return FDB_DATEI
    return FDB_EINGEBAUT if os.path.exists(FDB_EINGEBAUT) else None


def fdb_info(pfad=None):
    pfad = pfad or fdb_pfad()
    if not pfad:
        return {"vorhanden": False}
    try:
        with open(pfad, encoding="utf-8") as f:
            d = json.load(f)
    except Exception as e:
        return {"vorhanden": False, "fehler": str(e)}
    return {"vorhanden": True, "stand": d.get("stand"), "marken": len(d.get("b", [])), "farben": len(d.get("c", [])),
            "barcodes": len(d.get("g", {})), "quelle": "auf dem Server gespeichert" if pfad == FDB_DATEI else "im Container mitgeliefert",
            "geladen": time.strftime("%Y-%m-%d %H:%M", time.localtime(os.path.getmtime(pfad)))}


def fdb_aktualisieren():
    import urllib.request
    try:
        with urllib.request.urlopen(urllib.request.Request(FDB_URL or web.cdn_basis() + "filamentdb.json", headers={"User-Agent": "SchichtLohn-Server"}), timeout=60) as r:
            roh = r.read()
    except Exception as e:
        raise Fehler(502, "Download fehlgeschlagen (Internet an der Synology?): " + str(e))
    try:
        d = json.loads(roh.decode("utf-8"))
        assert isinstance(d.get("c"), list) and isinstance(d.get("l"), list) and isinstance(d.get("b"), list) and len(d["c"]) > 1000
    except Exception:
        raise Fehler(502, "Die geladene Datenbank ist unvollständig, die bisherige bleibt erhalten")
    alt = fdb_info().get("stand")
    if alt and d.get("stand") == alt and os.path.exists(FDB_DATEI):
        info = fdb_info(FDB_DATEI)
        info["vorher"] = alt
        return info  # schon aktuell, nichts ersetzen
    tmp = FDB_DATEI + ".neu"
    with open(tmp, "wb") as f:
        f.write(roh)
    os.replace(tmp, FDB_DATEI)
    info = fdb_info(FDB_DATEI)
    info["vorher"] = alt
    melden({"typ": "filamentdb", "stand": info.get("stand")})
    return info


# Automatisch: beim Start (nach 1 Minute) und dann alle 6 Stunden App und Filament-Datenbank holen
AUTO = {"geprueft": None, "fehler": None, "alle_h": 6}


def auto_aktualisieren():
    time.sleep(60)
    while True:
        fehler = []
        try:
            fdb_aktualisieren()
        except Exception as e:
            fehler.append("Filament-Datenbank: " + str(getattr(e, "text", e)))
        try:
            vorher = web.app_info(WEB).get("stand")
            info = web.aktualisieren(WEB)
            if info.get("stand") != vorher:
                melden({"typ": "app", "stand": info.get("stand")})
        except Exception as e:
            fehler.append("App: " + str(e))
        AUTO["geprueft"] = time.strftime("%Y-%m-%d %H:%M")
        AUTO["fehler"] = "; ".join(fehler) or None
        time.sleep(AUTO["alle_h"] * 3600)


def sicherung():
    con = db()
    listen = {}
    for (name,) in con.execute("SELECT DISTINCT liste FROM eintraege"):
        listen[name] = liste_lesen(name)
    daten = {k: json.loads(w) for k, w in con.execute("SELECT schluessel, wert FROM daten")}
    return {"dienst": "schichtlohn-server", "version": VERSION, "zeit": time.strftime("%Y-%m-%dT%H:%M:%S"), "listen": listen, "daten": daten}

# ---------------------------------------------------------------- Live-Meldungen

_hoerer = set()
_hoerer_lock = threading.Lock()


def melden(ev):
    with _hoerer_lock:
        for q in list(_hoerer):
            try:
                q.put_nowait(ev)
            except queue.Full:
                pass

# ---------------------------------------------------------------- Etikett-Leser

_ocr = None
_ocr_lock = threading.Lock()


_ocr_lade_lock = threading.Lock()
_ocr_genau = None


def ocr(genau=False):
    """Lesemodell wählen:
    Standard: PaddleOCR PP-OCRv4 mobil (schnell und genauer als das eingebaute v3).
    LESEMODELL=genau: zusätzlich das große PP-OCRv4-Server-Modell für Ausschnitte (nur für starke Rechner).
    LESEMODELL=standard: nur das eingebaute PP-OCRv3."""
    global _ocr, _ocr_genau
    modus = os.environ.get("LESEMODELL", "auto")
    det = os.path.join(MODELLE, "ocr_det.onnx")
    mobil, gross = os.path.join(MODELLE, "ocr_rec_mobil.onnx"), os.path.join(MODELLE, "ocr_rec.onnx")
    with _ocr_lade_lock:  # jedes Modell nur einmal laden
        from rapidocr_onnxruntime import RapidOCR
        if genau and modus == "genau" and os.path.exists(det) and os.path.exists(gross):
            if _ocr_genau is None:
                _ocr_genau = RapidOCR(det_model_path=det, rec_model_path=gross)
                print("Lesemodell geladen: PP-OCRv4 Server (genau)", flush=True)
            return _ocr_genau
        if _ocr is None:
            if modus != "standard" and os.path.exists(det) and os.path.exists(mobil):
                _ocr = RapidOCR(det_model_path=det, rec_model_path=mobil)
                print("Lesemodell geladen: PP-OCRv4 mobil", flush=True)
            else:
                _ocr = RapidOCR()
                print("Lesemodell geladen: PP-OCRv3 (eingebaut)", flush=True)
        return _ocr


# ---------------------------------------------------------------- Fingerabdruck (Aussehen der Spule)
# MobileNetV2 liefert für jedes Foto 1280 Merkmale (Form, Lochmuster, Etikett-Layout, Farben).
# Ordnet man ein Foto einer Sorte zu, wird der Fingerabdruck gespeichert; spätere Fotos
# werden damit verglichen. Gelernt wird nur aus den eigenen Fotos.

_merkmal = None
_merkmal_lock = threading.Lock()
_vid_cache = {}
_vid_reihe = []


def merkmal_sitzung():
    global _merkmal
    if _merkmal is None:
        if not os.path.exists(MERKMAL_MODELL):
            _merkmal = False
        else:
            import onnxruntime as ort
            _merkmal = ort.InferenceSession(MERKMAL_MODELL, providers=["CPUExecutionProvider"])
    return _merkmal or None


def lesemodell_name():
    m = os.environ.get("LESEMODELL", "auto")
    if m == "standard" or not os.path.exists(os.path.join(MODELLE, "ocr_rec_mobil.onnx")):
        return "PP-OCRv3"
    return "PP-OCRv4 + Server-Modell für Ausschnitte" if m == "genau" and os.path.exists(os.path.join(MODELLE, "ocr_rec.onnx")) else "PP-OCRv4"


def fingerabdruck(img):
    import numpy as np
    from PIL import ImageOps
    sitz = merkmal_sitzung()
    if sitz is None:
        return None
    x = np.asarray(ImageOps.fit(img, (224, 224)), dtype=np.float32) / 255.0
    x = ((x - [0.485, 0.456, 0.406]) / [0.229, 0.224, 0.225]).transpose(2, 0, 1)[None].astype(np.float32)
    with _merkmal_lock:
        v = sitz.run(["464"], {"input": x})[0].reshape(-1)
    n = float(np.linalg.norm(v)) or 1.0
    return (v / n).astype(np.float16)


def vid_merken(v):
    vid = uuid.uuid4().hex[:16]
    _vid_cache[vid] = v
    _vid_reihe.append(vid)
    while len(_vid_reihe) > 300:
        _vid_cache.pop(_vid_reihe.pop(0), None)
    return vid


def aehnliche(v, grenze=0.72, anzahl=6):
    import numpy as np
    rows = db().execute("SELECT uid, vek FROM abdruecke").fetchall()
    if not rows:
        return []
    M = np.stack([np.frombuffer(b, dtype=np.float16) for _, b in rows]).astype(np.float32)
    sc = M @ v.astype(np.float32)
    best = {}
    for (uid, _), x in zip(rows, sc):
        if x >= grenze and x > best.get(uid, 0):
            best[uid] = float(x)
    return [{"uid": u, "score": round(x, 3)} for u, x in sorted(best.items(), key=lambda t: -t[1])[:anzahl]]


def abdruck_speichern(uid, vid):
    v = _vid_cache.get(vid)
    if v is None:
        raise Fehler(404, "Fingerabdruck abgelaufen, bitte Foto neu aufnehmen")
    with _db_lock:
        con = db()
        con.execute("INSERT INTO abdruecke(uid, vek, zeit) VALUES(?,?,?)", (uid, v.tobytes(), time.time()))
        alte = con.execute("SELECT id FROM abdruecke WHERE uid=? ORDER BY zeit DESC LIMIT -1 OFFSET 20", (uid,)).fetchall()
        for (i,) in alte:
            con.execute("DELETE FROM abdruecke WHERE id=?", (i,))
        n = con.execute("SELECT COUNT(*) FROM abdruecke WHERE uid=?", (uid,)).fetchone()[0]
    return {"ok": True, "anzahl": n}

# ---------------------------------------------------------------- Farbe des Filaments
# Kräftige Farben in der Bildmitte zählen am meisten; ein weißes Etikett oder eine weiße Spule
# gleicht das Licht ab. Liefert bis zu drei Vorschläge – die App lässt den richtigen antippen.


def _kmeans(X, w, k=5, it=12):
    import numpy as np
    rng = np.random.default_rng(0)
    k = min(k, len(X))
    C = X[rng.choice(len(X), k, replace=False, p=w / w.sum())]
    for _ in range(it):
        lab = ((X[:, None, :] - C[None]) ** 2).sum(-1).argmin(1)
        for j in range(k):
            m = lab == j
            if m.any():
                C[j] = (X[m] * w[m, None]).sum(0) / w[m].sum()
    return C, lab


def farben(img):
    import numpy as np
    im = img.copy()
    im.thumbnail((200, 200))
    a = np.asarray(im, dtype=np.float32) / 255.0
    h, wd, _ = a.shape

    def satwert(x):
        mx = x.max(2)
        return (mx - x.min(2)) / np.maximum(mx, 1e-6), mx
    sat, mx = satwert(a)
    weiss = (mx > 0.75) & (sat < 0.12)
    if weiss.sum() > h * wd * 0.01:
        ref = a[weiss].mean(0)
        a = np.clip(a * np.clip(ref.mean() / np.maximum(ref, 1e-3), 0.8, 1.25), 0, 1)
        sat, mx = satwert(a)
    yy, xx = np.mgrid[0:h, 0:wd]
    cw = np.exp(-((((yy - h / 2) / h) ** 2 + ((xx - wd / 2) / wd) ** 2) / 0.38 ** 2))
    hex_ = lambda c: "#%02x%02x%02x" % tuple(int(max(0, min(1, v)) * 255) for v in c)
    out = []
    m = (sat > 0.18) & (mx > 0.35)  # auch Pastelltöne (Rosa, Hellblau …)
    if m.sum() >= h * wd * 0.004:
        X, W = a[m], cw[m] * sat[m] ** 1.5 * mx[m] ** 2  # helle, kräftige Farben zählen mehr als Haut und Schatten
        C, lab = _kmeans(X, W + 1e-6)
        sc = sorted(((W[lab == j].sum(), j) for j in range(len(C)) if (lab == j).any()), reverse=True)
        out += [hex_(C[j]) for _, j in sc[:3]]
    # unbunte Kandidaten (Schwarz, Weiß, Grau) aus der Bildmitte
    mitte = a[h // 3:2 * h // 3, wd // 3:2 * wd // 3].reshape(-1, 3)
    s2, _ = satwert(mitte[None])
    grau = mitte[s2[0] < 0.2]
    if len(grau) > 20 and len(out) < 4:
        C, lab = _kmeans(grau, np.ones(len(grau)), k=2)
        j = np.bincount(lab).argmax()
        out.append(hex_(C[j]))
    return out[:4]

# ---------------------------------------------------------------- Bild auswerten


def bild_lesen(daten, ausschnitt=False):
    import numpy as np
    from PIL import Image, ImageOps
    img = ImageOps.exif_transpose(Image.open(io.BytesIO(daten))).convert("RGB")
    if max(img.size) > MAX_SEITE:
        img.thumbnail((MAX_SEITE, MAX_SEITE))
    codes = []
    try:
        import zxingcpp
        for kandidat in (img, ImageOps.autocontrast(img.convert("L"))):
            for r in zxingcpp.read_barcodes(kandidat):
                t = (r.text or "").strip()
                if t and t not in codes:
                    codes.append(t)
            if codes:
                break
    except Exception:
        pass
    zeilen = []
    if OCR_AN:
        def lesen(bild, genau=False):
            t0 = time.time()
            modell = ocr(genau=genau)
            with _ocr_lock:
                res, _ = modell(np.asarray(bild)[:, :, ::-1])
            print(f"Gelesen in {time.time() - t0:.1f} s ({'Ausschnitt' if ausschnitt else 'Foto'}{', genau' if genau else ''}, {bild.size[0]}×{bild.size[1]})", flush=True)
            z = []
            for box, t, p in res or []:
                try:
                    p = float(p)
                except (TypeError, ValueError):
                    p = 0.0
                if p < 0.4 or not str(t).strip():
                    continue
                xs = [pt[0] for pt in box]
                ys = [pt[1] for pt in box]
                z.append({"t": str(t).strip(), "p": round(p, 3),
                          "box": [int(min(xs)), int(min(ys)), int(max(xs) - min(xs)), int(max(ys) - min(ys))]})
            return z
        if ausschnitt and max(img.size) > 1000:
            img.thumbnail((1000, 1000))  # Ausschnitt reicht in 1000 px, das genaue Modell bleibt so schnell
        zeilen = []
        if ausschnitt:
            try:
                zeilen = lesen(img, genau=True)
            except Exception as e:  # z. B. zu wenig Speicher für das genaue Modell
                print("Genaues Lesen fehlgeschlagen, nehme schnelles:", e, flush=True)
        if not zeilen:
            zeilen = lesen(img)
        if ausschnitt and len(zeilen) < 4:
            # blasser oder schräger Druck: weitere Versuche mit verstärktem Kontrast und leicht gedreht
            kon = ImageOps.autocontrast(img.convert("L"), cutoff=1).convert("RGB")
            gesehen = {z["t"] for z in zeilen}
            for bild in (kon, kon.rotate(-25, expand=True, fillcolor="white"), kon.rotate(25, expand=True, fillcolor="white"),
                         kon.rotate(90, expand=True), kon.rotate(270, expand=True), kon.rotate(180)):
                for z in lesen(bild):
                    if z["t"] not in gesehen:
                        gesehen.add(z["t"])
                        zeilen.append(z)
                if len(zeilen) >= 4:
                    break
    r = {"text": zeilen, "codes": codes, "w": img.size[0], "h": img.size[1]}
    if not ausschnitt:
        try:
            r["farben"] = farben(img)
        except Exception:
            r["farben"] = []
        try:
            v = fingerabdruck(img)
            if v is not None:
                r["vid"] = vid_merken(v)
                r["aehnlich"] = aehnliche(v)
        except Exception as e:
            print("Fingerabdruck:", e, flush=True)
    return r

# ---------------------------------------------------------------- HTTP


class Fehler(Exception):
    def __init__(self, code, text):
        super().__init__(text)
        self.code = code


# ---------------------------------------------------------------- Server-Einstellungen (Drucker, Bambu-Cloud, Home Assistant)
# Liegen in der Tabelle daten unter „_server“; über /api/daten nicht lesbar, Schlüssel werden nur maskiert ausgegeben.

EINST_KEY = "_server"
GEHEIM = ("code", "token")
MASKE = "••••••"


def einstellungen():
    w, _ = daten_lesen(EINST_KEY)
    w = w if isinstance(w, dict) else {}
    w.setdefault("drucker", [])
    w.setdefault("cloud", {})
    w.setdefault("ha", {})
    w.setdefault("telegram", {})
    w.setdefault("abbuchung", True)
    w.setdefault("fertig_meldung", True)
    w.setdefault("fach_meldung", True)
    w.setdefault("fach_link", "/schichtlohn-app")
    w.setdefault("waage_url", "")
    w.setdefault("preise", {})
    w["preise"].setdefault("ebay", {})
    w["preise"].setdefault("ali", {})
    return w


def einstellungen_maskiert():
    import copy
    e = copy.deepcopy(einstellungen())
    for d in e["drucker"]:
        if d.get("code"):
            d["code"] = MASKE
    for k in ("cloud", "ha", "telegram"):
        if e[k].get("token"):
            e[k]["token"] = MASKE
    e["cloud"].pop("uid", None)
    for k in ("ebay", "ali"):
        if e["preise"][k].get("secret"):
            e["preise"][k]["secret"] = MASKE
    return e


def einstellungen_setzen(neu):
    alt = einstellungen()
    e = dict(alt)
    if isinstance(neu.get("drucker"), list):
        if not neu["drucker"] and alt["drucker"] and not neu.get("drucker_leeren"):
            raise Fehler(409, "Die Druckerliste würde ganz geleert – abgebrochen. Bitte die Seite neu laden und noch einmal versuchen.")
        alte = {d.get("id"): d for d in alt["drucker"]}
        nach_serie = {str(d.get("serial") or "").upper(): d for d in alt["drucker"] if d.get("serial")}
        liste = []
        for d in neu["drucker"]:
            d = {k: (v.strip() if isinstance(v, str) else v) for k, v in d.items()}
            vorher = alte.get(d.get("id")) or nach_serie.get(str(d.get("serial") or "").upper()) or {}
            d["id"] = d.get("id") or vorher.get("id") or uuid.uuid4().hex[:8]
            # Fehlt eine Angabe ganz (z. B. beim Übernehmen aus der Bambu-Cloud), die bisherige behalten – IP und Zugangscode gehen so nicht verloren
            if "ip" not in d and vorher.get("ip"):
                d["ip"] = vorher["ip"]
            if not d.get("code") and vorher.get("code"):  # ein leerer Zugangscode ist nie gewollt
                d["code"] = vorher["code"]
            if d.get("code") == MASKE:
                d["code"] = vorher.get("code", "")
            if d.get("serial"):
                d["serial"] = d["serial"].upper()
                if not d.get("modell"):
                    d["modell"] = drucker_mod.modell_aus_serie(d["serial"])
            liste.append(d)
        e["drucker"] = liste
    for k in ("cloud", "ha", "telegram"):
        if isinstance(neu.get(k), dict):
            x = dict(alt[k])
            for kk, v in neu[k].items():
                if v == MASKE:
                    continue
                x[kk] = v.strip() if isinstance(v, str) else v
            if k == "cloud" and neu[k].get("token") not in (None, MASKE):
                x.pop("uid", None)
            e[k] = x
    if "abbuchung" in neu:
        e["abbuchung"] = bool(neu["abbuchung"])
    if isinstance(neu.get("preise"), dict):
        pr = {k: dict(v) for k, v in alt["preise"].items()}
        for k in ("ebay", "ali"):
            for kk, v in (neu["preise"].get(k) or {}).items():
                if kk in ("id", "secret", "key", "tracking") and v != MASKE:
                    pr.setdefault(k, {})[kk] = str(v or "").strip()
                if kk == "versand":  # Versandpauschale, wenn der Händler keinen Versand nennt
                    try:
                        pr.setdefault(k, {})["versand"] = max(0.0, min(50.0, round(float(str(v).replace(",", ".")), 2))) if str(v).strip() else None
                    except ValueError:
                        pass
        e["preise"] = pr
    if "fertig_meldung" in neu:
        e["fertig_meldung"] = bool(neu["fertig_meldung"])
    if "fach_meldung" in neu:
        e["fach_meldung"] = bool(neu["fach_meldung"])
    if "fach_link" in neu:
        e["fach_link"] = str(neu["fach_link"] or "").strip()[:200] or "/schichtlohn-app"
    nur_extras = set(neu) <= {"fertig_meldung", "fach_meldung", "fach_link", "waage_url", "preise", "telegram"}
    if "waage_url" in neu:
        u = str(neu["waage_url"] or "").strip().rstrip("/")[:120]
        if u and not re.match(r"^https?://", u):
            u = "http://" + u
        e["waage_url"] = u
    daten_schreiben(EINST_KEY, e)
    if isinstance(neu.get("preise"), dict):
        im_hintergrund(preise_abrufen, "Schlüssel gespeichert")
    if not nur_extras:
        BAMBU.neu_starten()
    return einstellungen_maskiert()


# ---------------------------------------------------------------- Zustände (wie Home Assistant: Drucker, AMS, Waage)

_zst = {}
_zst_lock = threading.Lock()


def zustand_setzen(eid, state, attrs, quelle=""):
    jetzt = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    with _zst_lock:
        alt = _zst.get(eid)
        if alt and alt["state"] == state and alt["attributes"] == attrs:
            return alt
        z = {"entity_id": eid, "state": state, "attributes": attrs, "last_changed": jetzt if not alt or alt["state"] != state else alt["last_changed"],
             "last_updated": jetzt}
        _zst[eid] = z
    melden({"typ": "zustand", "z": z, "quelle": quelle})
    return z


def zustaende_liste():
    with _zst_lock:
        return list(_zst.values())


def ha_cfg():
    h = einstellungen()["ha"]
    if (not h.get("url") or not h.get("token")) and HA_APP:
        # Als Home-Assistant-App: direkter Zugang über den Supervisor, ohne eigenen Token
        return "http://supervisor/core", os.environ["SUPERVISOR_TOKEN"]
    return (h.get("url") or "").rstrip("/"), h.get("token") or ""


def ha_anfrage(pfad, daten=None, timeout=10, roh=False):
    import urllib.request
    url, token = ha_cfg()
    if not url or not token:
        raise Fehler(503, "Home Assistant ist im Server nicht eingetragen")
    req = urllib.request.Request(url + pfad, data=None if daten is None else json.dumps(daten).encode(),
                                 headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"},
                                 method="GET" if daten is None else "POST")
    ctx = None
    if url.startswith("https://"):
        import ssl
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
        b = r.read()
    return b if roh else json.loads(b.decode() or "null")


def lan_netze(hinweis_ip="", besucher=""):
    """Welche Heimnetze (erste drei Zahlen der IP) nach Druckern durchsucht werden – höchstens vier."""
    import ipaddress
    import socket
    netze = []

    def dazu(ip):
        try:
            a = ipaddress.ip_address(str(ip).split(",")[0].strip())
        except ValueError:
            return
        if a.version != 4 or not a.is_private or str(a).startswith(("172.17.", "172.30.", "172.31.", "127.")):
            return  # Docker-/Supervisor-Netze ausnehmen
        n = ".".join(str(a).split(".")[:3])
        if n not in netze:
            netze.append(n)

    def host(u):
        m = re.match(r"^\w+://([^/:]+)", u or "")
        if m:
            try:
                dazu(socket.gethostbyname(m.group(1)))
            except OSError:
                pass
    if hinweis_ip:
        teile = [t for t in hinweis_ip.strip().split(".") if t][:3]
        if len(teile) == 3:
            dazu(".".join(teile) + ".1")
    for d in einstellungen()["drucker"]:
        if d.get("ip"):
            dazu(d["ip"])
    dazu(besucher)
    host(einstellungen().get("waage_url"))
    host(ha_cfg()[0])
    try:
        host((ha_anfrage("/api/config", timeout=5) or {}).get("internal_url"))
    except Exception:
        pass
    for n in ("192.168.178", "192.168.1", "192.168.0"):  # übliche FritzBox- und Router-Netze
        if n not in netze:
            netze.append(n)
    return netze[:4]


def im_hintergrund(f, *a):
    def lauf():
        try:
            f(*a)
        except Exception as e:
            print("Hintergrund:", e, flush=True)
    threading.Thread(target=lauf, daemon=True).start()


PREISE_KEY = "_preisvergleich"
PROTOKOLL_KEY = "_preisprotokoll"  # die letzten Abrufe: Zeit, Anlass, Dauer, Ergebnis je Sorte
PROTOKOLL_MAX, PROTOKOLL_DETAILS = 30, 5
_preise_lock = threading.Lock()
PREISE_STAND = {"laeuft": False}


def protokoll_schreiben(lauf):
    alt, _ = daten_lesen(PROTOKOLL_KEY)
    liste = [lauf] + [x for x in (alt if isinstance(alt, list) else []) if isinstance(x, dict)]
    for x in liste[PROTOKOLL_DETAILS:]:  # Einzelheiten nur für die letzten Abrufe aufheben
        x.pop("zeilen", None)
    daten_schreiben(PROTOKOLL_KEY, liste[:PROTOKOLL_MAX])


def preise_abrufen(anlass="automatisch"):
    """Aktuelle eBay- und AliExpress-Angebote für alle Sorten im Lager holen (täglich und nach dem Eintragen der Schlüssel)."""
    cfg = einstellungen().get("preise") or {}
    if not any(all((cfg.get(k) or {}).get(x) for x in f) for k, f in (("ebay", ("id", "secret")), ("ali", ("key", "secret")))):
        return None
    if not _preise_lock.acquire(blocking=False):
        return None
    start = time.time()
    PREISE_STAND["laeuft"] = True
    melden({"typ": "preise", "laeuft": True})
    try:
        alt, _ = daten_lesen(PREISE_KEY)
        alt = alt if isinstance(alt, dict) else {}
        sorten = []
        for it in liste_lesen(ENT):
            d = _desc(it)
            if not d.get("typ") and it.get("status") != "completed":
                sorten.append((it["uid"], d))
        try:
            werte, stat = preise_mod.abrufen(cfg, sorten, alt.get("werte"))
        except Exception as e:
            protokoll_schreiben({"zeit": time.strftime("%Y-%m-%d %H:%M:%S"), "anlass": anlass, "dauer": round(time.time() - start),
                                 "sorten": len(sorten), "ebay": 0, "ali": 0, "fehler": str(e)[:300]})
            raise
        neu = {"stand": time.strftime("%Y-%m-%d %H:%M"), "werte": werte, "ebay": stat["ebay"], "ali": stat["ali"],
               "sorten": len(sorten), "fehler": "; ".join(dict.fromkeys(stat["fehler"])) or None}
        daten_schreiben(PREISE_KEY, neu)
        protokoll_schreiben({"zeit": time.strftime("%Y-%m-%d %H:%M:%S"), "anlass": anlass, "dauer": round(time.time() - start),
                             "sorten": len(sorten), "ebay": stat["ebay"], "ali": stat["ali"], "fehler": neu["fehler"],
                             "dienste": [k for k, f in (("ebay", ("id", "secret")), ("ali", ("key", "secret"))) if all((cfg.get(k) or {}).get(x) for x in f)],
                             "zeilen": stat["zeilen"]})
        print(f"Preisvergleich: {stat['ebay']} eBay, {stat['ali']} AliExpress bei {len(sorten)} Sorten"
              + (f" – {neu['fehler']}" if neu["fehler"] else ""), flush=True)
        return neu
    finally:
        PREISE_STAND["laeuft"] = False
        _preise_lock.release()
        melden({"typ": "preise", "laeuft": False})


def preise_auto():
    time.sleep(180)
    while True:
        try:
            preise_abrufen()
        except Exception as e:
            print("Preisvergleich:", e, flush=True)
        time.sleep(24 * 3600)


def waage_weiter(was, methode, rumpf):
    """Etikettendruck über die Filamentwaage (bambu-scale): SchichtLohn reicht das fertige Raster an die Waage weiter."""
    import urllib.request
    basis = einstellungen().get("waage_url") or ""
    if not basis:
        raise Fehler(400, "Keine Waage eingetragen (Einstellungen → Funktionen → Spulen-Etiketten)")
    if (was, methode) == ("drucker", "GET"):
        return waage_drucker(basis)
    pfade = {("drucken", "POST"): "/api/etikett/drucken", ("etikett", "GET"): "/api/etikett/einstellungen",
             ("zustand", "GET"): "/api/zustand"}
    pfad = pfade.get((was, methode))
    if not pfad:
        raise Fehler(404, "Unbekannt")
    if rumpf is not None:
        rumpf = {k: rumpf[k] for k in ("breite", "hoehe", "daten", "kopien", "drucker", "titel", "dpi") if k in rumpf}
    req = urllib.request.Request(basis + pfad, method=methode, headers={"Content-Type": "application/json"},
                                 data=json.dumps(rumpf).encode() if rumpf is not None else None)
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read().decode("utf-8") or "{}")
    except Exception as e:
        grund = getattr(e, "reason", None) or e
        raise Fehler(502, f"Waage unter {basis} nicht erreichbar ({getattr(grund, 'strerror', None) or grund}). "
                          "Läuft sie, und steht in ihrer config.toml unter [server] adresse = \"0.0.0.0\"?")


def waage_drucker(basis):
    """Liste der Etikettendrucker: die Waage nennt ihre Adresse in Home Assistant, dort stehen die Drucker."""
    import urllib.request
    try:
        with urllib.request.urlopen(basis + "/api/etikett/einstellungen", timeout=8) as r:
            ha = (json.loads(r.read().decode("utf-8") or "{}").get("bruecke") or "").rstrip("/")
        if not ha:
            return {"ok": True, "drucker": []}
        with urllib.request.urlopen(ha + "/drucker", timeout=8) as r:
            d = json.loads(r.read().decode("utf-8") or "{}")
        return {"ok": True, "drucker": d.get("drucker") or []}
    except Exception:  # noqa: BLE001 – ältere Waage oder Integration: dann gibt es eben keine Auswahl
        return {"ok": True, "drucker": []}


# ------------------------------------------------------------ Druckwerte ergänzen
# Füllt im Lager nur LEERE Felder: Düse, Bett, Flow, K (Pressure Advance), max. Volumenstrom.
# Reihenfolge: Slicerprofil der Marke (OrcaSlicer/Bambu Studio) → SchichtLohn-Datenbank (nur Temperaturen)
# → Standardwert des Materials (Median aller Slicerprofile, ohne K). Eigene Werte bleiben unangetastet.
SW_DATEI = os.path.join(os.path.dirname(os.path.abspath(DB_PFAD)), "slicerwerte.json")
SW_MERKMALE = {"matt": "matte", "seide": "silk", "hf": "hf", "holz": "wood", "marmor": "marble", "glitzer": "sparkle",
               "leuchtend": "glow", "transparent": "translucent", "metallic": "metal", "basic": "basic", "tough+": "tough+",
               "tough": "tough", "cf": "cf", "gf": "gf", "lite": "lite", "galaxy": "galaxy", "silk+": "silk+", "pro": "pro",
               "schäumend": "foam", "esd": "esd", "high speed": "hs"}
SW_FELDER = ("duese_min", "duese_max", "bett_min", "bett_max", "flow", "k", "mvs")


def _sw_marke(t):
    t = str(t or "").lower().replace("ß", "ss")
    for w in ("3d", "filament", "lab", "tech", "polymers", "printing"):
        t = re.sub(r"\b" + w + r"\b", " ", t)
    return re.sub(r"[^a-z0-9]+", "", t)


def _sw_material(t):
    t = str(t or "").upper().replace(" ", "-")
    return t


def _sw_basis(m):
    for b in ("PETG-CF", "PLA-CF", "PETG", "PCTG", "PLA", "ABS", "ASA", "TPU", "PC", "PA"):
        if re.search(r"(^|[^A-Z])" + b.replace("-", "[- ]?") + r"([^A-Z]|X|\+|$)", m) or m.startswith(b):
            return b
    if m.startswith("PET"):
        return "PETG"
    return "PLA" if "PLA" in m else None


def slicerwerte(neu_laden=False):
    import urllib.request
    if neu_laden or not os.path.exists(SW_DATEI):
        with urllib.request.urlopen(urllib.request.Request(web.cdn_basis() + "tools/slicerwerte.json",
                                                           headers={"User-Agent": "SchichtLohn-Server"}), timeout=60) as r:
            roh = r.read()
        d = json.loads(roh.decode("utf-8"))
        if not d.get("profile"):
            raise Fehler(502, "Slicerwerte unvollständig")
        with open(SW_DATEI + ".neu", "wb") as f:
            f.write(roh)
        os.replace(SW_DATEI + ".neu", SW_DATEI)
    with open(SW_DATEI, encoding="utf-8") as f:
        return json.load(f)


def _sw_profil(sw, marke, material, merkmale):
    """Bestes Slicerprofil derselben Marke und desselben Materials; Merkmale (Matt, Seide …) entscheiden."""
    mk, mt = _sw_marke(marke), _sw_material(material)
    if not mk:
        return None
    gesucht = {SW_MERKMALE.get(str(x).lower(), str(x).lower()) for x in merkmale or []}
    erlaubt = {mt, _sw_basis(mt)}
    erlaubt |= {t + "-" + f.upper() for t in list(erlaubt) if t for f in ("cf", "gf") if f in gesucht}
    if mt.startswith("PA"):
        erlaubt |= {"PA", "PAHT", "PA6", "PA12"} | {x + "-CF" for x in ("PA", "PAHT", "PA6", "PA12")}
    kandidaten = [p for p in sw["profile"] if _sw_marke(p[0]) == mk and _sw_material(p[1]) in erlaubt
                  and "support" not in p[2].lower()]
    if not kandidaten:
        return None

    # Faserverstärkt (CF/GF) verhält sich anders – nur ein Profil mit derselben Faser passt
    faser = {f for f in ("cf", "gf") if f in gesucht}
    kandidaten = [p for p in kandidaten if {f for f in ("cf", "gf") if re.search(r"(^|[^a-z])" + f + r"([^a-z]|$)", (p[1] + " " + p[2]).lower())} == faser]
    if not kandidaten:
        return None

    def wert(p):
        n = p[2].lower()
        treffer = sum(1 for g in gesucht if g and g in n) + (1 if mt.lower() in n.replace("-", "") else 0)
        fremd = sum(1 for g in set(SW_MERKMALE.values()) if g in n and g not in ("pro", "basic")
                    and not any(g in x for x in gesucht))
        return (treffer - fremd, -len(n))
    return max(kandidaten, key=wert)


def _sw_datenbank(marke, material, merkmale):
    """Temperaturen aus der SchichtLohn-Datenbank (Open Filament Database, SpoolmanDB, Händler)."""
    pfad = fdb_pfad()
    if not pfad:
        return None
    try:
        with open(pfad, encoding="utf-8") as f:
            d = json.load(f)
    except Exception:
        return None
    mk, mt = _sw_marke(marke), _sw_material(material)
    marken = {i for i, b in enumerate(d.get("b", [])) if _sw_marke(b) == mk}
    linien = [l for l in d.get("l", []) if l[0] in marken and _sw_material(l[1]) == mt and l[4] and l[5]]
    if not linien:
        return None
    gesucht = {str(x).lower() for x in merkmale or []}
    linien.sort(key=lambda l: (-sum(1 for g in gesucht if g in str(l[2]).lower()), len(str(l[2]))))
    l = linien[0]
    return [l[4], l[5], l[6] or None, l[7] or None]


def werte_ergaenzen(vorschau=False, neu_laden=False):
    sw = slicerwerte(neu_laden)
    stat = {"eintraege": 0, "geaendert": 0, "felder": 0, "profil": 0, "datenbank": 0, "standard": 0, "ohne": [], "beispiele": []}
    for it in liste_lesen(ENT):
        stat["eintraege"] += 1
        try:
            d = json.loads(it["description"] or "{}")
        except ValueError:
            continue
        if not isinstance(d, dict):
            continue
        leer = [f for f in SW_FELDER if d.get(f) in (None, "", -1)]
        if not leer:
            continue
        marke, material, merkmale = d.get("hersteller"), d.get("material"), d.get("besonderheiten") or []
        neu, quelle, standard = {}, [], []
        p = _sw_profil(sw, marke, material, merkmale)
        if p:
            for f, v in zip(SW_FELDER, p[3:]):
                if f in leer and v is not None:
                    neu[f] = v
            quelle.append("Slicerprofil " + p[2])
            stat["profil"] += 1
        rest = [f for f in leer if f not in neu]
        if any(f in rest for f in SW_FELDER[:4]):
            t = _sw_datenbank(marke, material, merkmale)
            if t:
                for f, v in zip(SW_FELDER[:4], t):
                    if f in rest and v is not None:
                        neu[f] = v
                quelle.append("SchichtLohn-Datenbank")
                stat["datenbank"] += 1
        rest = [f for f in leer if f not in neu and f != "k"]  # K hängt am Drucker – nie als Standardwert
        basis = _sw_basis(_sw_material(material))
        mat = sw.get("material", {})
        faser = [f for f in ("CF", "GF") if f.lower() in {str(x).lower() for x in merkmale}]
        schluessel = [k + "-" + f for k in (_sw_material(material), basis) if k for f in faser] + [_sw_material(material), basis]
        mschl = next((k for k in schluessel if k and mat.get(k)), None)
        m = mat.get(mschl) if mschl else None
        if rest and m:
            for f, v in zip(SW_FELDER, m):
                if f in rest and v is not None:
                    neu[f] = v
                    standard.append(f)
            if standard:
                quelle.append("Standardwert " + mschl)
                stat["standard"] += 1
        if not neu:
            stat["ohne"].append(it["summary"])
            continue
        for f, v in neu.items():
            d[f] = int(v) if f.startswith(("duese", "bett")) else v
        if standard:
            d["werte_standard"] = sorted(set(d.get("werte_standard") or []) | set(standard))
        d["werte_quelle"] = " · ".join(quelle)
        stat["geaendert"] += 1
        stat["felder"] += len(neu)
        if len(stat["beispiele"]) < 15:
            stat["beispiele"].append({"spule": it["summary"], "neu": neu, "quelle": d["werte_quelle"]})
        if not vorschau:
            liste_aendern(ENT, "update_item", {"item": it["uid"], "description": json.dumps(d, ensure_ascii=False)})
    stat["ohne"] = stat["ohne"][:40]
    stat["vorschau"] = vorschau
    return stat


# ---------------------------------------------------------------- Telegram (Handy-Meldungen auch ohne Home Assistant)
# Bot bei @BotFather anlegen, Token eintragen, dem Bot einmal „/start“ schreiben – SchichtLohn findet die Chat-ID selbst.
def telegram_anfrage(methode, daten, token=None, roh=None, typ=None):
    import urllib.request
    import urllib.error
    # Beim Kopieren aus Telegram rutschen leicht Leerzeichen oder Umbrüche in den Token
    token = re.sub(r"\s+", "", token or einstellungen()["telegram"].get("token") or "")
    if not token:
        raise Fehler(400, "Kein Telegram-Bot eingetragen")
    req = urllib.request.Request("https://api.telegram.org/bot%s/%s" % (token, methode), method="POST",
                                 data=roh if roh is not None else json.dumps(daten).encode(),
                                 headers={"Content-Type": typ or "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=40) as r:
            d = json.loads(r.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as ex:
        try:
            d = json.loads(ex.read().decode("utf-8") or "{}")
        except ValueError:
            d = {}
        grund = str(d.get("description") or ex).replace(token, "…")
        if "Unauthorized" in grund or "Not Found" in grund:
            grund = "Der Token stimmt nicht – bitte noch einmal aus der BotFather-Nachricht kopieren"
        raise Fehler(502, "Telegram: " + grund)
    except Exception as ex:
        raise Fehler(502, "Telegram nicht erreichbar (Internet?): " + str(ex).replace(token, "…"))
    if not d.get("ok"):
        raise Fehler(502, "Telegram: " + str(d.get("description") or "unbekannter Fehler"))
    return d.get("result")


def telegram_chat_finden():
    """Chat-ID aus der letzten Nachricht an den Bot (der Nutzer schreibt ihm einmal /start)."""
    for u in reversed(telegram_anfrage("getUpdates", {"limit": 20}) or []):
        m = u.get("message") or u.get("my_chat_member") or {}
        chat = m.get("chat") or {}
        if chat.get("id"):
            name = chat.get("title") or " ".join(x for x in (chat.get("first_name"), chat.get("last_name")) if x) or chat.get("username") or ""
            return {"chat": str(chat["id"]), "name": name}
    raise Fehler(404, "Noch keine Nachricht an den Bot – schreib ihm in Telegram einmal /start und versuch es dann nochmal")


def telegram_foto(chat, foto, beschriftung):
    """Foto als Datei hochladen – für Bilder, die nur im Heimnetz liegen (Druckerkamera, Vorschaubild aus HA)."""
    grenze = uuid.uuid4().hex
    name, art = ("bild.png", "image/png") if foto[:4] == b"\x89PNG" else ("bild.jpg", "image/jpeg")
    teile = [("--%s\r\nContent-Disposition: form-data; name=\"%s\"\r\n\r\n%s\r\n" % (grenze, k, v)).encode("utf-8")
             for k, v in (("chat_id", chat), ("caption", beschriftung[:1000]), ("parse_mode", "HTML"))]
    teile.append(("--%s\r\nContent-Disposition: form-data; name=\"photo\"; filename=\"%s\"\r\nContent-Type: %s\r\n\r\n"
                  % (grenze, name, art)).encode() + foto + b"\r\n")
    teile.append(("--%s--\r\n" % grenze).encode())
    telegram_anfrage("sendPhoto", None, roh=b"".join(teile), typ="multipart/form-data; boundary=" + grenze)


def telegram_senden(titel, text, bild="", foto=None):
    t = einstellungen()["telegram"]
    if not (t.get("token") and t.get("chat")) or t.get("aus"):
        return False
    nachricht = "<b>%s</b>\n%s" % (html_esc(titel), html_esc(text))
    if foto:
        try:
            telegram_foto(t["chat"], foto, nachricht)
            return True
        except Exception as ex:
            print("Telegram-Foto:", ex, flush=True)
    if bild and re.match(r"^https?://", bild):
        try:
            telegram_anfrage("sendPhoto", {"chat_id": t["chat"], "photo": bild, "caption": nachricht[:1000], "parse_mode": "HTML"})
            return True
        except Exception:
            pass  # Bild nicht erreichbar (z. B. nur im Heimnetz) – dann nur Text
    telegram_anfrage("sendMessage", {"chat_id": t["chat"], "text": nachricht, "parse_mode": "HTML"})
    return True


def html_esc(t):
    return str(t or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def handy_meldung(titel, text, bild="", foto=None, aktionen=None, tag="", hinweis_id="filament_abbuchung"):
    """aktionen: Knöpfe der Handy-App, z. B. [{"action": "URI", "title": "…", "uri": "/schichtlohn-app?…"}].
    tag: gleiche Kennung ersetzt eine ältere Meldung auf dem Handy statt eine weitere anzuhängen."""
    melden({"typ": "meldung", "titel": titel, "text": text})
    im_hintergrund(telegram_senden, titel, text, bild, foto)
    h = einstellungen()["ha"]
    roh = h.get("notify") or ""
    ziele = [z.strip() for z in (roh if isinstance(roh, list) else str(roh).split(",")) if z.strip().startswith("notify.")]
    url, token = ha_cfg()
    if not (url and token):
        return
    if ziele:
        for ziel in ziele:  # mehrere Handys: an jedes einzeln
            nachricht = {"title": titel, "message": text}
            daten = {}
            if bild:  # iOS und Android zeigen das Bild in der Meldung
                daten.update({"image": bild, "attachment": {"url": bild, "content-type": "png"}})
            if aktionen:
                daten["actions"] = aktionen
            if tag:
                daten.update({"tag": tag, "group": "filament"})
            if daten:
                nachricht["data"] = daten
            im_hintergrund(ha_anfrage, "/api/services/notify/" + ziel[7:], nachricht)
    else:
        im_hintergrund(ha_anfrage, "/api/services/persistent_notification/create",
                       {"title": titel, "message": text, "notification_id": tag or hinweis_id})


# ---------------------------------------------------------------- Abbuchung nach Druckende (wie script.filament_abbuchen in HA)

ENT, META = "todo.filament", "todo.filament_verbrauch"


def _desc(it):
    try:
        d = json.loads(it.get("description") or "{}")
        return d if isinstance(d, dict) else {}
    except ValueError:
        return {}


def _zahl(x, std=0.0):
    try:
        return float(x)
    except (TypeError, ValueError):
        return std


def sorte_fuer(fid, col):
    """Sorte mit passender Bambu-ID und Bestand, bei mehreren die mit der nächsten Farbe (hex oder gelernte AMS-Farben)."""
    beste, abst = None, 10 ** 9
    for it in liste_lesen(ENT):
        if it["status"] == "completed":
            continue
        d = _desc(it)
        if not fid or str(d.get("bambu_id") or "") != fid or int(_zahl(d.get("spulen"))) <= 0:
            continue
        farben = [d.get("hex") or "#888888"] + [x for x in (d.get("ams_farben") or []) if isinstance(x, str)]
        dist = min(drucker_mod.farbunterschied(h, col) if col else 0 for h in farben)
        if dist < abst:
            beste, abst = (it, d), dist
    if beste and abst <= drucker_mod.FARB_TOL:
        return beste, ""
    if beste:
        return None, f"Farbe {col} passt zu keiner Sorte mit Bambu-ID {fid}"
    return None, f"keine Sorte mit Bambu-ID {fid or '?'} und Bestand"


def abbuchen_rechnen(d, gramm):
    gw = _zahl(d.get("gewicht"), 1000) or 1000
    sp = int(_zahl(d.get("spulen"), 1))
    rq = d.get("reste") if isinstance(d.get("reste"), list) else ([d["rest"]] if d.get("rest") not in (None, "") else [])
    rl = sorted(x for x in (_zahl(r) for r in rq) if 0 < x < gw)[:max(sp, 0)]
    g = gramm
    for _ in range(25):
        if g > 0 and sp > 0:
            if not rl:
                rl = [gw]
            elif rl[0] - g >= 1:
                rl = [rl[0] - g] + rl[1:]
                g = 0
            else:
                g = max(g - rl[0], 0)
                rl = rl[1:]
                sp -= 1
    neu = {k: v for k, v in d.items() if k != "rest"}
    neu.update({"v": 2, "spulen": sp, "reste": [int(round(x)) for x in rl if round(x) < gw],
                "refills": min(int(_zahl(d.get("refills"), 0)), sp)})
    bestand = ((sp - len(neu["reste"][:sp])) * gw + sum(neu["reste"][:sp])) if sp > 0 else 0
    return neu, bestand



# ---------------------------------------------------------------- Rolle je AMS-Fach
# Jede Sorte kann je Fach eine eigene Rolle führen: faecher = {"<Drucker>|<Ort>": {"g": Gramm, "seit": …, "quelle": "voll"|"gramm"|"waage"}}.
# Die Rolle im Fach ist eine der Spulen der Sorte; ist sie angebrochen, steht ihr Gewicht auch in „reste“.
# Nach einem Druck zieht der Server genau von der Rolle im benutzten Fach ab, sonst wie bisher von der leersten angebrochenen.

def fach_key(drucker, ort):
    return f"{drucker}|{ort}"


def _reste_liste(d):
    gw = _zahl(d.get("gewicht"), 1000) or 1000
    rq = d.get("reste") if isinstance(d.get("reste"), list) else ([d["rest"]] if d.get("rest") not in (None, "") else [])
    return [int(round(x)) for x in (_zahl(r) for r in rq) if 0 < x < gw], gw


def _naechster(liste, wert):
    if not liste:
        return None
    i = min(range(len(liste)), key=lambda k: abs(liste[k] - wert))
    return i if abs(liste[i] - wert) <= 3 else None


def _ohne_fachrollen(d, gramm):
    """Wie abbuchen_rechnen, aber die Rollen, die gerade in einem Fach stecken, bleiben unberührt."""
    reste, gw = _reste_liste(d)
    fach = [float(v["g"]) for v in (d.get("faecher") or {}).values() if isinstance(v, dict) and v.get("g") is not None and float(v["g"]) < gw]
    gesperrt = []
    for r in fach:
        i = _naechster(reste, r)
        if i is not None:
            gesperrt.append(reste.pop(i))
    sp = int(_zahl(d.get("spulen"), 1))
    frei = max(0, sp - len(gesperrt) - sum(1 for v in (d.get("faecher") or {}).values() if isinstance(v, dict) and v.get("g") is not None and float(v["g"]) >= gw))
    if frei <= 0:  # alle Spulen stecken in Fächern: von der ersten Fachrolle abbuchen, damit ihr Wert mitläuft
        k = next((k for k, v in (d.get("faecher") or {}).items() if isinstance(v, dict) and v.get("g") is not None), None)
        if k:
            neu, bestand, _ = rolle_abbuchen(d, gramm, *k.split("|", 1), tiefe=4)
            return neu, bestand
        return abbuchen_rechnen(d, gramm)
    tmp = dict(d, reste=reste, spulen=frei)
    neu, _ = abbuchen_rechnen(tmp, gramm)
    neu["spulen"] = int(neu["spulen"]) + (sp - frei)
    neu["reste"] = list(neu.get("reste") or []) + [int(x) for x in gesperrt]
    neu["refills"] = min(int(_zahl(d.get("refills"), 0)), neu["spulen"])
    return neu, abbuchen_rechnen(neu, 0)[1]


def rolle_abbuchen(d, gramm, drucker, ort, tiefe=0):
    """→ (neue Daten, Bestand, Rest der Rolle im Fach oder None)."""
    key = fach_key(drucker, ort)
    f = (d.get("faecher") or {}).get(key) if isinstance(d.get("faecher"), dict) else None
    if not f or f.get("g") is None or int(_zahl(d.get("spulen"), 1)) <= 0:
        neu, bestand = _ohne_fachrollen(d, gramm)
        return neu, bestand, None
    reste, gw = _reste_liste(d)
    r = float(f["g"])
    nr = r - gramm
    neu = {k: v for k, v in d.items() if k != "rest"}
    faecher = dict(d.get("faecher") or {})
    i = _naechster(reste, r) if r < gw else None
    if nr > 2:
        if i is not None:
            reste[i] = int(round(nr))
        else:
            reste.append(int(round(nr)))
        faecher[key] = dict(f, g=round(nr, 1), zuletzt=time.strftime("%Y-%m-%dT%H:%M:%S"))
        neu.update({"v": 2, "reste": reste, "faecher": faecher})
        return neu, abbuchen_rechnen(neu, 0)[1], round(nr, 1)
    # Rolle leer: aus den Resten und der Spulenzahl nehmen, was übrig bleibt normal abbuchen
    if i is not None:
        reste.pop(i)
    faecher.pop(key, None)
    neu.update({"v": 2, "reste": reste, "faecher": faecher, "spulen": max(0, int(_zahl(d.get("spulen"), 1)) - 1)})
    neu["refills"] = min(int(_zahl(neu.get("refills"), 0)), neu["spulen"])
    uebrig = -nr if nr < 0 else 0
    if uebrig > 0.5:
        # Das AMS wechselt bei leerer Rolle auf dieselbe Sorte in einem anderen Fach – den Rest dort abbuchen (gleicher Drucker zuerst)
        andere = sorted((k for k, v in faecher.items() if isinstance(v, dict) and v.get("g") is not None), key=lambda k: (not k.startswith(drucker + "|"), k))
        if andere and tiefe < 4:
            dr2, ort2 = andere[0].split("|", 1)
            neu, bestand, _ = rolle_abbuchen(neu, uebrig, dr2, ort2, tiefe + 1)
            return neu, bestand, 0
        neu, bestand = _ohne_fachrollen(neu, uebrig)
        return neu, bestand, 0
    return neu, abbuchen_rechnen(neu, 0)[1], 0


def rolle_setzen(d, drucker, ort, aktion, gramm=None, quelle=""):
    """Rolle eines Fachs setzen: aktion voll | gramm | entfernen → neue Daten."""
    key = fach_key(drucker, ort)
    reste, gw = _reste_liste(d)
    faecher = dict(d.get("faecher") or {}) if isinstance(d.get("faecher"), dict) else {}
    alt = faecher.get(key)
    neu = {k: v for k, v in d.items() if k != "rest"}
    if aktion == "entfernen":
        faecher.pop(key, None)
    else:
        g = gw if aktion == "voll" else float(gramm)
        if g >= gw - 1:
            g = gw
        sp = int(_zahl(d.get("spulen"), 1))
        if g < gw:
            i = _naechster(reste, float(alt["g"])) if alt and alt.get("g") is not None and float(alt["g"]) < gw else None
            if i is not None:          # dieselbe Rolle neu gewogen
                reste[i] = int(round(g))
            elif sp > len(reste):      # eine volle Spule ist jetzt diese angebrochene Rolle
                reste.append(int(round(g)))
            elif reste:                # alle Spulen schon angebrochen: die passendste ersetzen
                j = min(range(len(reste)), key=lambda k: abs(reste[k] - g))
                reste[j] = int(round(g))
            else:
                reste.append(int(round(g)))
                neu["spulen"] = max(sp, 1)
        faecher[key] = {"g": round(g, 1), "seit": time.strftime("%Y-%m-%dT%H:%M:%S"), "quelle": quelle or aktion}
    neu.update({"v": 2, "reste": reste, "faecher": faecher})
    return neu


def rollen_liste():
    """Alle belegten Fächer mit Sorte (wie bei der Abbuchung zugeordnet) und Rolle, falls bekannt."""
    out = []
    sorten = {it["uid"]: (it, _desc(it)) for it in liste_lesen(ENT) if it["status"] != "completed"}
    for eid, f in sorted(faecher_sammeln().items()):
        if f["leer"] or not f["fid"]:
            continue
        ort = fach_ort(eid)
        treffer, _ = sorte_fuer(f["fid"], f["col"])
        x = {"drucker": f["drucker"], "ort": ort, "key": fach_key(f["drucker"], ort)}
        if treffer:
            it, d = treffer
            r = (d.get("faecher") or {}).get(x["key"]) if isinstance(d.get("faecher"), dict) else None
            x.update({"uid": it["uid"], "sorte": it["summary"], "gewicht": _zahl(d.get("gewicht"), 1000) or 1000, "leer_g": _zahl(d.get("leer_g")) or None,
                      "rolle": r, "gleiche": [{"key": k, "g": v.get("g")} for k, v in (d.get("faecher") or {}).items() if k != x["key"] and isinstance(v, dict)]})
        out.append(x)
    return out

def _gram(g):
    return ("%.1f" % g).replace(".", ",")


# ---------------------------------------------------------------- Trocknungs-Hinweis
# Feuchteempfindliches Filament, das lange offen im AMS bzw. an der externen Spule hängt → einmal Meldung aufs Handy.
TROCKNEN_TAGE = [(("PVA", "BVOH"), 1), (("PA", "PAHT", "PA6", "PA12", "PPA", "NYLON"), 2), (("PC", "PET", "PPS"), 3), (("TPU", "TPE"), 4),
                 (("PETG", "PCTG", "ABS", "ASA", "HIPS"), 10)]
TROCKNEN_KEY = "_trocknen"
_trocknen = {"stand": None, "geaendert": False, "zuletzt": 0}


def _trocknen_tage(typ):
    t = str(typ or "").upper().replace("-", " ").split()
    if not t:
        return None
    for namen, tage in TROCKNEN_TAGE:
        if t[0] in namen or any(x in namen for x in t[:2]):
            return tage
    return None


def trocknen_pruefen(z):
    st = _trocknen
    if st["stand"] is None:
        w, _ = daten_lesen(TROCKNEN_KEY)
        st["stand"] = w if isinstance(w, dict) else {}
    jetzt = time.time()
    for eid, (s, a) in z.items():
        if not (("_ams_" in eid and "_slot_" in eid) or "externe_spule" in eid) or not isinstance(a, dict):
            continue
        if a.get("empty") or not a.get("type"):
            if st["stand"].pop(eid, None) is not None:
                st["geaendert"] = True
            continue
        key = "|".join(str(a.get(k) or "") for k in ("type", "color", "tag_uid", "filament_id"))
        alt = st["stand"].get(eid)
        if not alt or alt.get("k") != key:
            st["stand"][eid] = {"k": key, "t": jetzt, "m": 0}
            st["geaendert"] = True
            continue
        tage = _trocknen_tage(a.get("type"))
        if tage and not alt.get("m") and jetzt - alt["t"] > tage * 86400:
            alt["m"] = 1
            st["geaendert"] = True
            wo = str(a.get("friendly_name") or eid)
            d = int((jetzt - alt["t"]) // 86400)
            handy_meldung("Filament trocknen?", f"{a.get('name') or a.get('type')} steckt seit {d} Tagen offen in {wo}. "
                                                 f"{a.get('type')} zieht Feuchtigkeit – vor wichtigen Drucken trocknen oder in eine Trockenbox legen.")
    if st["geaendert"] and jetzt - st["zuletzt"] > 60:
        daten_schreiben(TROCKNEN_KEY, st["stand"])
        st["geaendert"], st["zuletzt"] = False, jetzt


def _dauer(s):
    s = int(s or 0)
    if s <= 0:
        return ""
    h, m = s // 3600, (s % 3600) // 60
    return f"{h} h {m} min" if h else f"{max(1, m)} min"


def ha_bild(pfad):
    """Bild aus Home Assistant (Kamera, Vorschaubild) – None, wenn kein HA da ist oder nichts kommt."""
    url, token = ha_cfg()
    if not (url and token):
        return None
    try:
        b = ha_anfrage(pfad, timeout=15, roh=True)
    except Exception:
        return None
    return b if b and len(b) > 500 and b[:1] in (b"\xff", b"\x89") else None


def kamera_foto(pre):
    return ha_bild(f"/api/camera_proxy/camera.{pre}_kamera")


# Druckverlauf je Drucker → Telegram: Start (Vorschaubild), 25/50/75 % und Pause (Kamerabild), neue HMS-Fehler.
# Ende und Abbruch meldet fertig_melden (mit Verbrauch).
DRUCK_STAND = {}
STUFEN = (25, 50, 75)


def druck_beobachten(dr):
    p = dr.p
    st = str(p.get("gcode_state") or "").upper()
    if not st:
        return
    pct = drucker_mod._int(p.get("mc_percent"), 0)
    job = "%s|%s" % (p.get("task_id") or "", p.get("subtask_name") or "")
    hms = {"%s_%s" % (h.get("attr"), h.get("code")) for h in (p.get("hms") or []) if isinstance(h, dict)}
    alt = DRUCK_STAND.get(dr.serial)
    if alt is None:  # erster Blick nach dem Serverstart: nur merken, nichts nachmelden
        DRUCK_STAND[dr.serial] = {"job": job, "st": st, "stufen": {x for x in STUFEN if pct >= x}, "hms": hms,
                                  "frei": st not in drucker_mod.LAUFEND}
        return
    meldungen = []
    codes = sorted(hms - alt["hms"])
    if st not in drucker_mod.LAUFEND:
        alt["frei"] = True  # nächster Druck darf wieder eine Startmeldung bekommen
    elif job != alt["job"] and alt["st"] in ("FINISH", "FAILED", "IDLE"):
        alt["frei"] = True
    alt["job"] = job
    if st == "RUNNING" and alt["frei"]:
        alt.update(frei=False, stufen={x for x in STUFEN if pct >= x})
        meldungen.append("start")
    if st == "RUNNING":
        neu = [x for x in STUFEN if pct >= x and x not in alt["stufen"]]
        alt["stufen"].update(neu)
        if neu and pct < 100:
            meldungen.append("stand")
    if st == "PAUSE" and alt["st"] == "RUNNING":
        meldungen.append("pause")
    if codes:
        meldungen.append("fehler")
    alt_st = alt["st"]
    alt["hms"], alt["st"] = hms, st
    if getattr(dr, "ha", False) and alt_st in drucker_mod.LAUFEND and st in ("FINISH", "FAILED"):
        meldungen.append("fertig" if st == "FINISH" else "abbruch")
    t = einstellungen()["telegram"]
    if not meldungen or not (t.get("token") and t.get("chat")) or t.get("aus") or t.get("druckverlauf") is False:
        return
    name = dr.d.get("name") or drucker_mod.MODELL_NAMEN.get(dr.d.get("modell") or "", dr.serial)
    pre = dr.d.get("praefix") or drucker_mod.praefix(dr.d)
    aufgabe = str(p.get("subtask_name") or "").strip() or "Druckauftrag"
    zeit = _zeittext(p)
    task = str(p.get("task_id") or "")
    for m in meldungen:
        im_hintergrund(druck_telegram, m, name, pre, aufgabe, pct, zeit, codes, dr.serial, task, dr)


def uhrzeit(ts):
    """Ortszeit als HH:MM – die Zeitzone kommt von Home Assistant (TZ), sonst Deutschland."""
    import datetime
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo(os.environ.get("TZ") or "Europe/Berlin")
    except Exception:
        return time.strftime("%H:%M", time.localtime(ts))
    return datetime.datetime.fromtimestamp(ts, tz).strftime("%H:%M")


def _zeittext(p):
    rest = drucker_mod._int(p.get("mc_remaining_time"), 0)
    ende = uhrzeit(time.time() + rest * 60) if rest else ""
    return (" · noch %s" % _dauer(rest * 60) if rest else "") + (" · fertig ca. %s Uhr" % ende if ende else "")


def druck_telegram(art, name, pre, aufgabe, pct, zeit, codes, serial, task, dr=None):
    if art == "start":
        time.sleep(25)  # Name, Restzeit und Vorschaubild stehen erst kurz nach dem Start fest
        if dr is not None:
            aufgabe = str(dr.p.get("subtask_name") or "").strip() or aufgabe
            zeit = _zeittext(dr.p) or zeit
        foto = ha_bild(f"/api/image_proxy/image.{pre}_titelbild")
        bild = ""
        c = einstellungen()["cloud"]
        if not foto and c.get("token"):
            try:
                bild = str((drucker_mod.cloud_aufgabe(c["token"], c.get("region", "global"), serial, task, aufgabe) or {}).get("cover") or "")
            except Exception:
                bild = ""
        telegram_senden(f"🟢 {name}: Druck gestartet", aufgabe + zeit, bild, foto)
    elif art == "stand":
        telegram_senden(f"{name}: {pct} % gedruckt", aufgabe + zeit, "", kamera_foto(pre))
    elif art == "pause":
        telegram_senden(f"⏸️ {name}: Druck pausiert", aufgabe + " – der Drucker wartet, vielleicht ist das Filament leer.",
                        "", kamera_foto(pre))
    elif art in ("fertig", "abbruch"):
        telegram_senden(("✅ %s: Druck fertig" if art == "fertig" else "❌ %s: Druck abgebrochen") % name, aufgabe,
                        "", kamera_foto(pre))
    elif art == "fehler":
        nr = [c for c in codes if not c.startswith("ha_")]
        telegram_senden(f"⚠️ {name} meldet einen Fehler", aufgabe + (" – HMS " + ", ".join(nr) if nr else "")
                        + "\nDetails in der Bambu-App oder am Drucker.", "", kamera_foto(pre))


# Ohne eigene Bambu-Verbindung (Cloud nicht angemeldet): Druckerwerte aus Home Assistant (ha-bambulab) lesen
HA_DRUCKER_VORLAGE = ("{% set ns = namespace(o=[]) %}{% for s in states.sensor if s.entity_id.endswith('_druckstatus') "
                      "and s.attributes.get('quelle') != 'schichtlohn' %}{% set p = s.entity_id[7:-12] %}"
                      "{% set ns.o = ns.o + [[p, s.state, states('sensor.' ~ p ~ '_druckfortschritt'), "
                      "states('sensor.' ~ p ~ '_verbleibende_zeit'), states('sensor.' ~ p ~ '_name_der_aufgabe'), "
                      "states('binary_sensor.' ~ p ~ '_hms_fehler'), states('sensor.' ~ p ~ '_startzeit')]] %}"
                      "{% endfor %}{{ ns.o | tojson }}")
HA_DRUCKER = {}


class _HaDrucker:
    ha = True

    def __init__(self, pre):
        self.serial = "ha:" + pre
        self.d = {"praefix": pre}
        self.p = {}


def ha_drucker_abfragen():
    url, token = ha_cfg()
    if not (url and token):
        return
    eigene = {dr.serial.lower() for dr in BAMBU.drucker.values() if dr.online}
    namen = {str(d.get("serial") or "").lower(): d.get("name") for d in einstellungen().get("drucker") or []}
    zeilen = json.loads(ha_anfrage("/api/template", {"template": HA_DRUCKER_VORLAGE}, timeout=15, roh=True).decode() or "[]")
    for pre, st, pct, rest, aufgabe, hms, start in zeilen:
        serie = pre.split("_", 1)[-1]
        if serie in eigene:  # läuft schon über die eigene Bambu-Verbindung
            continue
        dr = HA_DRUCKER.get(pre) or HA_DRUCKER.setdefault(pre, _HaDrucker(pre))
        dr.d["name"] = namen.get(serie) or pre.split("_")[0].upper()
        ok = lambda v: v not in ("unknown", "unavailable", "", None)
        try:
            rest_min = round(float(rest) * 60)
        except (TypeError, ValueError):
            rest_min = 0
        dr.p = {"gcode_state": st.upper() if ok(st) else "", "mc_percent": pct if ok(pct) else 0,
                "mc_remaining_time": rest_min, "subtask_name": aufgabe if ok(aufgabe) else "",
                "task_id": start if ok(start) else "", "hms": [{"attr": "ha", "code": "1"}] if hms == "on" else []}
        druck_beobachten(dr)


def ha_drucker_schleife():
    time.sleep(30)
    while True:
        try:
            ha_drucker_abfragen()
        except Exception as ex:
            print("Drucker aus HA:", ex, flush=True)
        time.sleep(20)


def fertig_melden(druckername, erg, kurz):
    """Eine Handymeldung zum Druckende: Auftrag, Drucker, Dauer, Verbrauch – mit Vorschaubild, wenn die Cloud eins hat."""
    aufgabe = (erg.get("aufgabe") or "").strip() or "Druckauftrag"
    titel = f"{erg['anlass']}: {aufgabe}"
    kopf = " · ".join(x for x in (druckername, _dauer(erg.get("dauer")),
                                  ("%d %%" % round(erg.get("anteil", 1) * 100)) if erg.get("anteil", 1) < 1 else "") if x)
    foto = kamera_foto(erg["praefix"]) if erg.get("praefix") else None
    handy_meldung(titel, kopf + (". " + ". ".join(kurz) if kurz else ""), erg.get("bild") or "", foto)


def druck_abbuchen(druckername, erg):
    e0 = einstellungen()
    fertig = e0.get("fertig_meldung", True)
    if not e0.get("abbuchung", True):
        print(f"{druckername}: {erg['anlass']} – automatische Abbuchung ist aus", flush=True)
        if fertig:
            fertig_melden(druckername, erg, [])
        return
    kurz = []
    zeit = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    dt = time.strftime("%d.%m.%Y %H:%M")
    bericht, offen, knapp = [], [], []
    app_posten, app_offen = [], []  # für die Meldung in der App
    for po in erg["posten"]:
        g = float(po.get("gramm") or 0)
        if g <= 0.05:
            continue
        treffer, grund = sorte_fuer(po.get("fid") or "", (po.get("col") or "").lower())
        if treffer:
            it, d = treffer
            vorher = abbuchen_rechnen(d, 0)[1]
            neu, bestand, rolle = rolle_abbuchen(d, g, druckername, po.get("ort") or "")
            liste_aendern(ENT, "update_item", {"item": it["uid"], "description": json.dumps(neu, ensure_ascii=False)})
            gw = _zahl(d.get("gewicht"), 1000) or 1000
            if bestand <= 0 < vorher:
                knapp.append(f"{it['summary']} ist aufgebraucht")
            elif bestand < gw <= vorher:
                knapp.append(f"{it['summary']}: nur noch {int(round(bestand))} g")
            preis = _zahl(d.get("preis"))
            log = {"typ": "verbrauch", "v": 1, "zeit": zeit, "drucker": druckername, "ort": po.get("ort") or "", "sorte": it["summary"],
                   "uid": it["uid"], "hersteller": d.get("hersteller") or "", "material": d.get("material") or "", "hex": d.get("hex") or "",
                   "gramm": round(g, 1), "preis": preis or None, "kosten": round(g / 1000 * preis, 2) if preis else None,
                   "anlass": erg["anlass"], "quelle": "SchichtLohn-Server · " + erg.get("quelle", ""),
                   "task": erg.get("task") or "", "aufgabe": erg.get("aufgabe") or ""}
            if rolle is not None:
                log["rolle_g"] = rolle
            gd = float(po.get("gramm_datei") or 0)
            if gd > g + 0.05:  # abgebrochen oder Teile übersprungen: Gesamtmenge laut Datei mitschreiben
                log["gramm_datei"] = round(gd, 1)
            if erg.get("uebersprungen"):
                log["uebersprungen"] = erg["uebersprungen"]
                log["skip_genau"] = bool(erg.get("skip_genau"))
                log["gramm_voll"] = round(float(po.get("gramm_voll") or g), 1)
            liste_aendern(META, "add_item", {"item": f"{dt} · {druckername} · {_gram(g)} g · {it['summary']}",
                                             "description": json.dumps(log, ensure_ascii=False)})
            bericht.append(f"{it['summary']}: −{_gram(g)} g ({po.get('ort')}), Bestand {int(round(bestand))} g")
            kurz.append(f"{_gram(g)} g {it['summary']}, noch {int(round(bestand))} g")
            app_posten.append({"sorte": it["summary"], "hex": d.get("hex") or "", "gramm": round(g, 1), "bestand": int(round(bestand))})
        else:
            kurz.append(f"{_gram(g)} g nicht zugeordnet ({po.get('ort')})")
            offen.append(f"{po.get('ort')} ({_gram(g)} g): {grund}")
            app_offen.append({"gramm": round(g, 1), "ort": po.get("ort") or ""})
            merk = {"typ": "offen", "v": 1, "gramm": round(g, 1), "drucker": druckername, "ort": po.get("ort") or "", "fid": po.get("fid") or "",
                    "farbe": po.get("col") or "", "name": po.get("name") or "", "material": po.get("material") or "", "grund": grund,
                    "anlass": erg["anlass"], "zeit": zeit}
            liste_aendern(ENT, "add_item", {"item": f"⚠ Nicht zugeordnet: {_gram(g)} g · {druckername} · {po.get('ort')}",
                                            "description": json.dumps(merk, ensure_ascii=False)})
    teile = []
    if bericht:
        teile.append("Abgebucht: " + "; ".join(bericht))
    if offen:
        teile.append("Nicht abgebucht (in SchichtLohn zuordnen): " + "; ".join(offen))
    if not erg["posten"]:
        teile.append("Keine Verbrauchsangaben gefunden (" + erg.get("quelle", "") + ")")
    n_skip = erg.get("uebersprungen") or 0
    if n_skip:
        gespart = sum(float(po.get("gramm_voll") or 0) - float(po.get("gramm") or 0) for po in erg["posten"])
        teil = f"{n_skip} Teil{'e' if n_skip > 1 else ''} übersprungen"
        if erg.get("skip_genau") and gespart > 0.05:
            hinweis = f"{teil}, dafür {_gram(gespart)} g weniger abgebucht"
        elif gespart > 0.05:
            hinweis = f"{teil}, geschätzt {_gram(gespart)} g weniger abgebucht – in SchichtLohn unter Druckaufträge → Verbrauch anpassen prüfen"
        else:
            hinweis = f"{teil} – Verbrauch nicht genau bekannt, in SchichtLohn unter Druckaufträge → Verbrauch anpassen korrigieren"
        teile.append(hinweis)
        kurz.append(hinweis.split(" – ")[0])
    anteil = erg.get("anteil", 1)
    text = f"{druckername}, {erg['anlass']}{' (%d %%)' % round(anteil * 100) if anteil < 1 else ''}. " + ". ".join(teile)
    print(text, flush=True)
    melden({"typ": "abbuchung", "drucker": druckername, "text": text, "aufgabe": erg.get("aufgabe") or "", "anlass": erg["anlass"],
            "posten": app_posten, "offen": app_offen})
    if fertig:
        fertig_melden(druckername, erg, kurz)
    else:
        handy_meldung("Filament abgebucht", text)
    if knapp:
        handy_meldung("Filament wird knapp", "; ".join(knapp) + ". Steht jetzt auf der Einkaufsliste in SchichtLohn.")


def abdruecke_export():
    import base64
    return [{"uid": u, "vek": base64.b64encode(b).decode(), "zeit": z} for u, b, z in db().execute("SELECT uid, vek, zeit FROM abdruecke")]


def umzug(quelle, token="", nur_daten=False):
    """Alles von einem anderen SchichtLohn-Server (z. B. der Synology) übernehmen.
    nur_daten: Lager, Drucke, Preise und App-Einstellungen, aber keine Zugänge (Server-Einstellungen mit eBay/AliExpress/Bambu/
    Telegram/Home Assistant/Druckercodes) und keine Claude-Adresse – z. B. für einen Freund, der mit deinem Lager startet."""
    import base64
    import urllib.request
    quelle = quelle.rstrip("/")
    if not re.match(r"^https?://", quelle):
        quelle = "http://" + quelle

    def holen(pfad, roh=False):
        req = urllib.request.Request(quelle + pfad, headers={"X-Token": token} if token else {})
        with urllib.request.urlopen(req, timeout=60) as r:
            b = r.read()
        return b if roh else json.loads(b.decode("utf-8"))
    try:
        s = holen("/api/sicherung")
    except Exception as e:
        raise Fehler(502, f"{quelle} nicht erreichbar oder kein SchichtLohn-Server: {e}")
    if s.get("dienst") != "schichtlohn-server":
        raise Fehler(400, "Unter dieser Adresse läuft kein SchichtLohn-Server")
    out = {"listen": {}, "daten": 0, "abdruecke": 0, "filamentdb": False}
    for name, items in (s.get("listen") or {}).items():
        liste_ersetzen(name, items)
        out["listen"][name] = len(items)
    for k, w in (s.get("daten") or {}).items():
        if k == ZUGANG_KEY:  # der neue Server behält seinen eigenen App-Schlüssel
            continue
        if nur_daten and k in (EINST_KEY, MCP_KEY):
            out.setdefault("ausgelassen", []).append(k)
            continue
        if k == EINST_KEY and isinstance(w, dict) and HA_APP:
            w.setdefault("ha", {})
        daten_schreiben(k, w, "umzug")
        out["daten"] += 1
    try:
        ab = holen("/api/abdruecke")
        with _db_lock:
            con = db()
            con.execute("DELETE FROM abdruecke")
            for a in ab:
                con.execute("INSERT INTO abdruecke(uid, vek, zeit) VALUES(?,?,?)", (a["uid"], base64.b64decode(a["vek"]), a.get("zeit") or time.time()))
        out["abdruecke"] = len(ab)
    except Exception:
        pass
    try:
        roh = holen("/filamentdb.json", roh=True)
        if len(roh) > 100000:
            with open(FDB_DATEI + ".neu", "wb") as f:
                f.write(roh)
            os.replace(FDB_DATEI + ".neu", FDB_DATEI)
            out["filamentdb"] = True
    except Exception:
        pass
    BAMBU.neu_starten()
    melden({"typ": "neu"})
    return out


class _Wirt:
    """Verbindet die Drucker (drucker.py) mit Lager und Zuständen."""

    def einstellungen(self):
        return einstellungen()

    def cloud(self):
        return dict(einstellungen()["cloud"])

    def cloud_merken(self, c):
        # Lesen und Schreiben unter einer Sperre – sonst können gleichzeitig startende Drucker einen
        # halben Stand zurückschreiben (so ging die Druckerliste samt IP-Adressen verloren)
        with _db_lock:
            w, _ = daten_lesen(EINST_KEY)
            if not isinstance(w, dict):
                return
            w.setdefault("cloud", {})["uid"] = c.get("uid")
            daten_schreiben(EINST_KEY, w)

    def zustaende(self, dr, z):
        for eid, (s, a) in z.items():
            zustand_setzen(eid, s, a, "drucker")
        try:
            trocknen_pruefen(z)
        except Exception as ex:
            print("Trocknen:", ex, flush=True)
        try:
            druck_beobachten(dr)
        except Exception as ex:
            print("Druckverlauf:", ex, flush=True)

    def druckende(self, dr, erg):
        name = dr.d.get("name") or drucker_mod.MODELL_NAMEN.get(dr.d.get("modell") or "", dr.serial)
        erg["praefix"] = drucker_mod.praefix(dr.d)
        vorschau = erg.pop("_vorschau", None)
        try:
            druck_merken(dr, name, erg, vorschau)
        except Exception as ex:
            print(f"{name}: Druck nicht ins Protokoll geschrieben: {ex}", flush=True)
        druck_abbuchen(name, erg)

    def log(self, text):
        print(text, flush=True)


# ---------------------------------------------------------------- Druckprotokoll des Servers und Druckerspeicher
# Jeder Druck, den der Server enden sieht (egal ob aus Bambu Studio übers Heimnetz oder über die Cloud gestartet),
# kommt mit Titel, Zeit, Gramm je Filament und Vorschaubild in eine Liste. Dazu liest der Server alle 6 Stunden die
# Druckdateien im Speicher der Drucker (IP und Zugangscode nötig) – so erscheinen auch ältere Drucke.
DRUCKE_KEY = "_drucke"
DRUCKE_MAX = 1000
SPEICHER_KEY = "_druckerspeicher"
SPEICHER_ALLE_H = 6
DRUCKBILDER = os.path.join(os.path.dirname(os.path.abspath(DB_PFAD)), "druckbilder")
DRUCKDATEIEN = os.path.join(os.path.dirname(os.path.abspath(DB_PFAD)), "druckdateien")
SPEICHER_STAND = {"laeuft": False}
_speicher_lock = threading.Lock()


def _bild_id(*teile):
    return hashlib.sha1("|".join(str(t) for t in teile).encode()).hexdigest()[:16]


def _bild_speichern(bid, daten):
    if not daten:
        return ""
    try:
        os.makedirs(DRUCKBILDER, exist_ok=True)
        with open(os.path.join(DRUCKBILDER, bid + ".png"), "wb") as f:
            f.write(daten)
        return bid
    except OSError:
        return ""


def _iso(t):
    return time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(t)) if t else ""


def druck_merken(dr, name, erg, vorschau=None):
    ende = time.time()
    start = erg.get("start") or (ende - erg.get("dauer", 0) if erg.get("dauer") else 0)
    did = _bild_id(dr.serial, int(ende))
    eintrag = {"id": did, "drucker": name, "serial": dr.serial, "praefix": erg.get("praefix") or "",
               "titel": erg.get("aufgabe") or "Druck", "start": _iso(start), "ende": _iso(ende),
               "minuten": round((ende - start) / 60) if start else round(erg.get("dauer", 0) / 60),
               "abgebrochen": erg.get("anlass") != "Druck fertig", "fortschritt": round((erg.get("anteil") or 1) * 100),
               "quelle": erg.get("quelle") or "", "uebersprungen": erg.get("uebersprungen") or 0,
               "filamente": [{"gramm": po.get("gramm") or 0, "farbe": po.get("col") or "", "typ": po.get("material") or "",
                              "name": po.get("name") or "", "ort": po.get("ort") or "", "fid": po.get("fid") or "",
                              **({"gramm_datei": po["gramm_datei"]} if (po.get("gramm_datei") or 0) > (po.get("gramm") or 0) + 0.05 else {})}
                             for po in erg.get("posten") or [] if (po.get("gramm") or 0) > 0],
               "bild": _bild_speichern(did, vorschau), "bild_url": erg.get("bild") or ""}
    eintrag["gramm"] = round(sum(f["gramm"] for f in eintrag["filamente"]), 2)
    if any(f.get("gramm_datei") for f in eintrag["filamente"]):
        eintrag["gramm_datei"] = round(sum(f.get("gramm_datei") or f["gramm"] for f in eintrag["filamente"]), 2)
    alt, _ = daten_lesen(DRUCKE_KEY)
    liste = [eintrag] + [x for x in (alt if isinstance(alt, list) else []) if isinstance(x, dict)]
    daten_schreiben(DRUCKE_KEY, liste[:DRUCKE_MAX])
    melden({"typ": "drucke"})


def _norm_titel(t):
    return re.sub(r"[^a-z0-9äöüß]+", "", re.sub(r"(\.gcode)?\.3mf$", "", str(t or "").lower()))


def drucke_ergaenzen():
    """Drucke ohne Gramm oder ohne Bild mit der passenden Druckdatei aus dem Druckerspeicher ergänzen
    (gleicher Name, am liebsten vom selben Drucker). Gramm und Zeit laut Datei, bei Abbruch anteilig."""
    sp, _ = daten_lesen(SPEICHER_KEY)
    idx = {}
    for serial, v in (sp if isinstance(sp, dict) else {}).items():
        for f in v.get("dateien") or []:
            if not f.get("fehler"):
                idx.setdefault(_norm_titel(f.get("titel")), []).append((serial.upper(), f))
    if not idx:
        return 0
    n = 0
    with _db_lock:
        liste, _ = daten_lesen(DRUCKE_KEY)
        liste = [x for x in (liste if isinstance(liste, list) else []) if isinstance(x, dict)]
        for x in liste:
            kand = idx.get(_norm_titel(x.get("titel")))
            if not kand or (x.get("gramm") and x.get("bild")):
                continue
            serial, f = next(((s_, f_) for s_, f_ in kand if s_ == str(x.get("serial") or "").upper()), kand[0])
            geaendert = False
            if not x.get("gramm") and f.get("gramm"):
                anteil = (x.get("fortschritt") or 100) / 100 if x.get("abgebrochen") else 1.0
                x["filamente"] = [{"gramm": round(m.get("gramm", 0) * anteil, 2), "farbe": m.get("farbe") or "", "typ": m.get("typ") or "",
                                   "name": m.get("typ") or "", "ort": "", "fid": m.get("fid") or ""} for m in f.get("filamente") or []]
                x["gramm"] = round(sum(m["gramm"] for m in x["filamente"]) or f["gramm"] * anteil, 2)
                x["gramm_quelle"] = "Druckdatei"
                geaendert = True
            if not x.get("minuten") and f.get("minuten"):
                x["minuten"] = f["minuten"]
                geaendert = True
            if not x.get("bild") and f.get("bild_id"):
                x["bild"] = f["bild_id"]
                geaendert = True
            if geaendert:
                x["datei"] = f.get("pfad") or ""
                n += 1
        if n:
            daten_schreiben(DRUCKE_KEY, liste)
    if n:
        melden({"typ": "drucke"})
        print(f"Druckprotokoll: {n} Drucke mit Druckdateien ergänzt", flush=True)
    return n


def archiv_info():
    anzahl, groesse = 0, 0
    for wurzel, _, dateien in os.walk(DRUCKDATEIEN):
        for d in dateien:
            if d.lower().endswith(".3mf"):
                anzahl += 1
                groesse += os.path.getsize(os.path.join(wurzel, d))
    return {"anzahl": anzahl, "mb": round(groesse / 1048576)}


def archiv_liste():
    """Alle gesicherten Druckdateien mit den Angaben aus dem Druckerspeicher (Titel, Zeit, Gramm, Bild) – auch die,
    die auf dem Drucker längst gelöscht sind."""
    sp, _ = daten_lesen(SPEICHER_KEY)
    sp = sp if isinstance(sp, dict) else {}
    out = []
    if not os.path.isdir(DRUCKDATEIEN):
        return out
    namen = {str(d.get("serial") or "").upper(): d.get("name") or drucker_mod.MODELL_NAMEN.get(drucker_mod.modell_aus_serie(d.get("serial")), "")
             for d in einstellungen().get("drucker") or []}
    for s_ in os.listdir(DRUCKDATEIEN):
        namen.setdefault(s_, drucker_mod.MODELL_NAMEN.get(drucker_mod.modell_aus_serie(s_), ""))
    for serial in sorted(os.listdir(DRUCKDATEIEN)):
        ordner = os.path.join(DRUCKDATEIEN, serial)
        if not os.path.isdir(ordner):
            continue
        info = sp.get(serial) or {}
        meta = {os.path.basename(f.get("pfad") or ""): f for f in info.get("dateien") or [] if isinstance(f, dict)}
        for name in os.listdir(ordner):
            if not name.lower().endswith(".3mf"):
                continue
            pf = os.path.join(ordner, name)
            m = meta.get(name) or {}
            st = os.stat(pf)
            out.append({"serial": serial, "drucker": info.get("drucker") or namen.get(serial) or serial, "name": name,
                        "titel": m.get("titel") or re.sub(r"(\.gcode)?\.3mf$", "", name, flags=re.I),
                        "groesse": st.st_size, "zeit": m.get("zeit") or st.st_mtime, "minuten": m.get("minuten") or 0,
                        "gramm": m.get("gramm") or 0, "filamente": m.get("filamente") or [], "bild_id": m.get("bild_id") or "",
                        "auf_drucker": bool(m)})
    out.sort(key=lambda x: -(x["zeit"] or 0))
    return out


_MODELL_IDS = {}  # printer_model_id aus den 3MF → Modell, gelernt aus dem Archiv (jede Datei liegt im Ordner des Druckers, der sie gedruckt hat)


def modell_ids_lernen():
    if _MODELL_IDS.get("_fertig"):
        return _MODELL_IDS
    if os.path.isdir(DRUCKDATEIEN):
        for serial in os.listdir(DRUCKDATEIEN):
            ordner = os.path.join(DRUCKDATEIEN, serial)
            if not os.path.isdir(ordner):
                continue
            m = drucker_mod.modell_aus_serie(serial)
            for name in sorted(os.listdir(ordner))[:12]:
                try:
                    with open(os.path.join(ordner, name), "rb") as f:
                        mid = drucker_mod.modell_id(f.read())
                except OSError:
                    continue
                if mid:
                    _MODELL_IDS.setdefault(mid, set()).add(m)
    _MODELL_IDS["_fertig"] = True
    return _MODELL_IDS


def archiv_datei(serial, name):
    serial = re.sub(r"[^A-Z0-9]", "", str(serial or "").upper())
    name = os.path.basename(str(name or ""))
    pf = os.path.join(DRUCKDATEIEN, serial, name)
    if not serial or not name.lower().endswith(".3mf") or not os.path.exists(pf):
        raise Fehler(404, "Druckdatei nicht gesichert")
    with open(pf, "rb") as f:
        return serial, name, f.read()


# Allgemeine Bambu-Profile, wenn eine Sorte keine eigene Bambu-ID hat (Material → ID, Düsentemperatur min/max)
GENERISCH = {"PLA": ("GFL99", 190, 230), "PLA+": ("GFL99", 200, 230), "PETG": ("GFG99", 220, 260), "PCTG": ("GFG97", 230, 260),
             "ABS": ("GFB99", 240, 270), "ASA": ("GFB98", 240, 270), "TPU": ("GFU99", 200, 250), "PA": ("GFN99", 260, 290),
             "PC": ("GFC99", 260, 280), "PVA": ("GFS99", 190, 210), "HIPS": ("GFS98", 220, 240), "PET": ("GFG99", 230, 260)}


def fach_belegen(k):
    """Ein AMS-Fach am Drucker auf eine Sorte aus dem Lager setzen."""
    name = str(k.get("drucker") or "")
    dr = next((d for d in BAMBU.drucker.values() if d.serial == name or (d.info().get("name") or "") == name), None)
    if not dr:
        raise Fehler(404, "Drucker nicht verbunden")
    fach = next((f for f in drucker_mod.faecher(dr.p) if f["ort"] == k.get("ort") or str(f["global"]) == str(k.get("fach"))), None)
    if not fach:
        raise Fehler(404, "Fach nicht gefunden")
    it = next((x for x in liste_lesen(ENT) if x["uid"] == k.get("uid")), None)
    if not it:
        raise Fehler(404, "Sorte nicht im Lager")
    d = _desc(it)
    mat = str(d.get("material") or "PLA").upper().split()[0]
    basis = re.sub(r"[-+ ].*$", "", mat) if mat not in GENERISCH else mat
    gid, gmin, gmax = GENERISCH.get(mat) or GENERISCH.get(basis) or GENERISCH["PLA"]
    fid = str(d.get("bambu_id") or "").strip() or gid
    tmin = int(_zahl(d.get("duese_min")) or gmin)
    tmax = int(_zahl(d.get("duese_max")) or gmax)
    try:
        b = dr.fach_setzen(fach, fid, d.get("hex") or "#888888", basis if basis in GENERISCH else mat, tmin, tmax)
    except RuntimeError as e:
        raise Fehler(409, str(e))
    return {"ok": True, "ort": fach["ort"], "sorte": it["summary"], "tray_info_idx": fid, "typ": b["tray_type"], "farbe": b["tray_color"],
            "duese": [tmin, tmax], "eigene_id": bool(str(d.get("bambu_id") or "").strip())}


def senden_pruefen(serial, name):
    """Für den Dialog „An Drucker senden“: Platten der Datei, passende Drucker und Vorschlag, welches Fach welches Filament druckt."""
    serial, name, daten = archiv_datei(serial, name)
    mid, platten = drucker_mod.datei_platten(daten)
    ids = modell_ids_lernen()
    herkunft = drucker_mod.modell_aus_serie(serial)
    erlaubt = set(ids.get(mid) or ()) or {herkunft}
    drucker = []
    for dr in BAMBU.drucker.values():
        modell = drucker_mod.modell_aus_serie(dr.serial, dr.d.get("modell") or "")
        fl = drucker_mod.faecher(dr.p)
        vorschlag = {}
        for pl in platten:
            z = []
            for fi, f in drucker_mod.zuordnen([x for x in pl["filamente"] if x["gramm"] > 0], fl):
                ok = bool(f) and (not fi["typ"] or f["typ"].upper() == fi["typ"].upper())
                z.append({"id": fi["id"], "typ": fi["typ"], "farbe": fi["farbe"], "gramm": fi["gramm"],
                          "fach": f["global"] if f else None, "ort": f["ort"] if f else "", "fach_typ": f["typ"] if f else "",
                          "fach_farbe": f["farbe"] if f else "", "fach_name": f["name"] if f else "", "ok": ok})
            vorschlag[pl["platte"]] = z
        drucker.append({"serial": dr.serial, "name": dr.info()["name"] or dr.serial, "modell": modell, "online": dr.online,
                        "status": str(dr.p.get("gcode_state") or ""), "lan": bool(dr.d.get("ip") and dr.d.get("code")),
                        "passt": modell in erlaubt, "faecher": [{"global": f["global"], "ort": f["ort"], "typ": f["typ"], "farbe": f["farbe"],
                                                                  "name": f["name"]} for f in fl if not f["leer"]],
                        "vorschlag": vorschlag})
    drucker.sort(key=lambda d: (not d["passt"], d["serial"] != serial, d["name"]))
    return {"name": name, "serial": serial, "modell_id": mid, "platten": platten, "drucker": drucker}


def senden(k):
    serial, name, daten = archiv_datei(k.get("serial"), k.get("name"))
    dr = BAMBU.drucker.get(str(k.get("ziel") or "").strip())
    if not dr:
        raise Fehler(404, "Drucker nicht gefunden")
    if not (dr.d.get("ip") and dr.d.get("code")):
        raise Fehler(409, "Für diesen Drucker fehlen IP-Adresse und Zugangscode (Heimnetz) – ohne die kann SchichtLohn keine Datei hochladen")
    mid = drucker_mod.modell_id(daten)
    erlaubt = set(modell_ids_lernen().get(mid) or ()) or {drucker_mod.modell_aus_serie(serial)}
    if drucker_mod.modell_aus_serie(dr.serial, dr.d.get("modell") or "") not in erlaubt and not k.get("trotzdem"):
        raise Fehler(409, "Die Datei ist für ein anderes Druckermodell geslict")
    starten = bool(k.get("starten"))
    if starten and str(dr.p.get("gcode_state") or "").upper() in drucker_mod.LAUFEND:
        raise Fehler(409, "Der Drucker druckt gerade")
    ziel = name if name.lower().endswith(".gcode.3mf") else re.sub(r"\.3mf$", ".gcode.3mf", name, flags=re.I)
    ok, text = drucker_mod.hochladen(dr.d["ip"], dr.d["code"], ziel, daten)
    if not ok:
        raise Fehler(502, text)
    if not starten:
        return {"ok": True, "hochgeladen": ziel, "gestartet": False}
    zu = {int(a): (None if b is None else int(b)) for a, b in (k.get("zuordnung") or {}).items()}
    try:
        dr.druck_starten(ziel, int(k.get("platte") or 1), zu, bool(k.get("zeitraffer")), k.get("kalibrieren", True) is not False)
    except RuntimeError as e:
        raise Fehler(409, f"Hochgeladen, aber nicht gestartet: {e}")
    return {"ok": True, "hochgeladen": ziel, "gestartet": True}


def drucke_importieren(neu):
    alt, _ = daten_lesen(DRUCKE_KEY)
    liste = [x for x in (alt if isinstance(alt, list) else []) if isinstance(x, dict)]
    ids = {x["id"] for x in neu}
    vorher = len(liste)
    liste = [x for x in liste if x.get("id") not in ids] + neu
    liste.sort(key=lambda x: str(x.get("ende") or x.get("start") or ""), reverse=True)
    daten_schreiben(DRUCKE_KEY, liste[:max(DRUCKE_MAX, len(neu) + 500)])
    melden({"typ": "drucke"})
    ergaenzt = drucke_ergaenzen()
    return {"ok": True, "uebernommen": len(neu), "neu": len(liste) - vorher, "gesamt": len(liste), "ergaenzt": ergaenzt}


def speicher_abrufen(anlass="automatisch"):
    """Druckdateien aller Drucker mit IP und Zugangscode auslesen."""
    if not _speicher_lock.acquire(blocking=False):
        return None
    SPEICHER_STAND["laeuft"] = True
    melden({"typ": "drucke", "laeuft": True})
    try:
        alt, _ = daten_lesen(SPEICHER_KEY)
        alt = alt if isinstance(alt, dict) else {}
        neu = {}
        for d in einstellungen().get("drucker") or []:
            serial = str(d.get("serial") or "").upper()
            if not serial or d.get("aktiv") is False:
                continue
            vorher = alt.get(serial) or {}
            name = d.get("name") or drucker_mod.MODELL_NAMEN.get(d.get("modell") or "", serial)
            if not (d.get("ip") and d.get("code")):
                neu[serial] = {"drucker": name, "stand": vorher.get("stand"), "fehler": "Keine IP-Adresse eingetragen",
                               "dateien": vorher.get("dateien") or []}
                continue
            bekannt = {x["pfad"]: x for x in vorher.get("dateien") or [] if isinstance(x, dict) and x.get("pfad")}
            try:
                liste = drucker_mod.speicher_lesen(d["ip"], d["code"], bekannt, ziel=os.path.join(DRUCKDATEIEN, re.sub(r"[^A-Z0-9]", "", serial)))
                for e in liste:
                    bild = e.pop("bild", None)
                    if bild:
                        e["bild_id"] = _bild_speichern(_bild_id(serial, e["pfad"], e["groesse"]), bild)
                    e["zeit_iso"] = _iso(e.get("zeit"))
                neu[serial] = {"drucker": name, "stand": time.strftime("%Y-%m-%d %H:%M"), "fehler": None, "dateien": liste}
                print(f"Druckerspeicher {name}: {len(liste)} Druckdateien", flush=True)
            except Exception as ex:
                neu[serial] = {"drucker": name, "stand": vorher.get("stand"), "fehler": drucker_mod.fehlertext(ex),
                               "dateien": vorher.get("dateien") or []}
                print(f"Druckerspeicher {name}: {ex}", flush=True)
        daten_schreiben(SPEICHER_KEY, neu)
        drucke_ergaenzen()
        return neu
    finally:
        SPEICHER_STAND["laeuft"] = False
        _speicher_lock.release()
        melden({"typ": "drucke", "laeuft": False})


def speicher_auto():
    time.sleep(240)
    while True:
        try:
            speicher_abrufen()
        except Exception as ex:
            print("Druckerspeicher:", ex, flush=True)
        time.sleep(SPEICHER_ALLE_H * 3600)


BAMBU = drucker_mod.Bambu(_Wirt())


# ---------------------------------------------------------------- MCP-Anbindung für Claude (server/mcp.py)
# Adresse: /mcp/<schlüssel>. Der Schlüssel steckt in der Adresse, weil claude.ai bei eigenen Konnektoren keine Kopfzeilen setzen kann;
# er wird beim ersten Abruf erzeugt und lässt sich über POST /api/mcp {"neu": true} erneuern (alte Adresse geht dann nicht mehr).
MCP_KEY = "_mcp"


def mcp_schluessel(neu=False):
    import secrets
    w, _ = daten_lesen(MCP_KEY)
    if neu or not isinstance(w, dict) or not w.get("schluessel"):
        w = {"schluessel": secrets.token_urlsafe(24), "seit": time.strftime("%Y-%m-%dT%H:%M:%S")}
        daten_schreiben(MCP_KEY, w, "mcp")
    return w["schluessel"]


mcp_mod.W = type("McpWirt", (), {})()
for _n, _v in {"liste_lesen": liste_lesen, "liste_aendern": liste_aendern, "abbuchen_rechnen": abbuchen_rechnen, "zustaende_liste": zustaende_liste,
               "daten_lesen": daten_lesen, "_desc": _desc, "_zahl": _zahl, "_gram": _gram, "ENT": ENT, "META": META, "DRUCKE_KEY": DRUCKE_KEY}.items():
    setattr(mcp_mod.W, _n, staticmethod(_v) if callable(_v) else _v)
BILDER = produktbilder.Bilder(os.path.join(os.path.dirname(os.path.abspath(DB_PFAD)), "produktbilder"),
                              lambda: (einstellungen().get("preise") or {}).get("ali") or {})


# ---------------------------------------------------------------- Fach prüfen (ersetzt script.filament_fach_pruefen in HA)
# Ändert sich in einem AMS-Fach oder an einer externen Spule Profil (filament_id) oder Farbe und bleibt 20 Sekunden so,
# prüft der Server gegen sein Lager, ob eine Sorte mit Bestand dazu passt (gleiche Bambu-ID, Farbe nah an Lagerfarbe
# oder gelernter AMS-Farbe). Wenn nicht, kommt eine Handymeldung mit bis zu drei Vorschlägen als Knöpfe.
# Ein Knopf öffnet SchichtLohn in Home Assistant und ordnet das Fach dort zu (Adresse mit ?sl_fach=…&sl_sorte=…).

FACH_RE = re.compile(r"_(?:ams_(\d+)_slot_(\d+)(?:_\d+)?|externalspool(\d*)_externe_spule)$")
FACH_RUHE = 20          # Sekunden, die ein neuer Fachinhalt gleich bleiben muss
FACH_TAKT = 10          # Sekunden zwischen zwei Durchläufen
FACH_TOL = drucker_mod.FARB_TOL  # gleiche Farbtoleranz wie Karte und Abbuchung
FACH_STAND = {}         # entity_id -> {"sig": bestätigter Inhalt, "neu": wartender Inhalt, "seit": Zeit}
FACH_GEMELDET = {}      # entity_id -> Inhalt, zu dem eine Meldung offen ist
HA_FAECHER_VORLAGE = (
    "{% set ns = namespace(o=[]) %}{% for s in states.sensor if (s.entity_id is search('_ams_\\d+_slot_\\d+(_\\d+)?$') "
    "or s.entity_id is search('_externalspool\\d*_externe_spule$')) and s.attributes.get('quelle') != 'schichtlohn' %}"
    "{% set pre = s.entity_id[7:] | regex_replace('_(ams_\\d+_slot_\\d+(_\\d+)?|externalspool\\d*_externe_spule)$', '') %}"
    "{% set d = device_id('sensor.' ~ pre ~ '_druckstatus') %}{% set ns.o = ns.o + [[s.entity_id, s.state, "
    "s.attributes.get('filament_id') or '', (s.attributes.get('color') or '')[:7], s.attributes.get('name') or '', "
    "s.attributes.get('type') or '', s.attributes.get('empty') == true, (device_attr(d, 'name_by_user') if d else '') or '']] %}"
    "{% endfor %}{{ ns.o | tojson }}")


KURZNAMEN = {"h2c": "H2C", "h2d": "H2D", "h2s": "H2S", "p1s": "P1S", "p1p": "P1P", "p2s": "P2S", "x1c": "X1C", "x1e": "X1E",
             "a1": "A1", "a1mini": "A1 mini"}


def _kurzname(pre):
    m = pre.split("_")[0]
    return KURZNAMEN.get(m, m.upper())


def _generic(fid):
    return bool(re.match(r"^GF.99$", fid or "", re.I))


def fach_ort(eid):
    m = FACH_RE.search(eid)
    if not m:
        return ""
    if m.group(1):
        a = int(m.group(1))
        return f"AMS HT {a - 127}" if a >= 128 else f"AMS {a} Fach {m.group(2)}"
    return "Externe Spule 2" if m.group(3) == "2" else "Externe Spule"


def faecher_sammeln():
    """Alle Fächer: eigene Drucker (MQTT) zuerst, dazu die Drucker, die nur Home Assistant kennt."""
    out = {}
    namen = {drucker_mod.praefix(d): d.get("name") for d in einstellungen().get("drucker") or []}
    for z in zustaende_liste():
        e, a = z["entity_id"], z["attributes"]
        if not (e.startswith("sensor.") and FACH_RE.search(e)):
            continue
        pre = e[7:].split("_ams_")[0].split("_externalspool")[0]
        out[e] = {"state": z["state"], "fid": str(a.get("filament_id") or ""), "col": str(a.get("color") or "")[:7].lower(),
                  "name": a.get("name") or z["state"], "typ": a.get("type") or "", "leer": a.get("empty") is True,
                  "drucker": namen.get(pre) or _kurzname(pre)}
    url, token = ha_cfg()
    if url and token:
        try:
            zeilen = json.loads(ha_anfrage("/api/template", {"template": HA_FAECHER_VORLAGE}, timeout=15, roh=True).decode() or "[]")
        except Exception as ex:
            print("Fächer aus HA:", ex, flush=True)
            zeilen = []
        for e, st, fid, col, name, typ, leer, dname in zeilen:
            if e in out:
                continue
            pre = e[7:].split("_ams_")[0].split("_externalspool")[0]
            out[e] = {"state": st, "fid": str(fid or ""), "col": str(col or "").lower(), "name": name or st, "typ": typ or "",
                      "leer": bool(leer), "drucker": dname or namen.get(pre) or _kurzname(pre)}
    return out


def fach_pruefen(eid, f, melden_=True):
    """Wie script.filament_fach_pruefen: {"status": "leer"|"zugeordnet"|"offen", …}"""
    fid, col = f["fid"], f["col"]
    if not fid or f["leer"] or str(f["state"]) in ("unavailable", "unknown", "Empty", "Leer", ""):
        return {"status": "leer"}
    generic = _generic(fid)
    mat = str(f["typ"]).split("-")[0].upper()
    treffer, tdist, mitid, kand = None, 10 ** 9, False, []
    for it in liste_lesen(ENT):
        if it["status"] == "completed":
            continue
        d = _desc(it)
        if d.get("typ") is not None or int(_zahl(d.get("spulen"))) <= 0:  # Merkzeilen und aufgebrauchte Sorten nicht
            continue
        farben = [d.get("hex") or "#888888"] + [x for x in (d.get("ams_farben") or []) if isinstance(x, str)]
        dist = min(drucker_mod.farbunterschied(h, col) if col else 0 for h in farben)
        gleich = str(d.get("bambu_id") or "") == fid and not generic
        if gleich:
            mitid = True
            if dist < tdist:
                treffer, tdist = it["summary"], dist
        score = dist + (0 if gleich else 10 ** 6) + (0 if str(d.get("material") or "").upper().startswith(mat) else 10 ** 7)
        kand.append((score, it["uid"], it["summary"]))
    if treffer is not None and tdist <= FACH_TOL:
        return {"status": "zugeordnet", "sorte": treffer}
    kand.sort()
    if generic:
        grund = f"Generic-Profil ({fid}) – in Bambu Studio erst das eigene Profil der Sorte wählen"
    elif mitid:
        grund = f"Profil {fid} bekannt, aber diese Farbe noch keiner Sorte zugeordnet"
    else:
        grund = f"Profil {fid} noch keiner Sorte im Lager zugeordnet"
    ort = fach_ort(eid)
    text = f"{f['drucker']} {ort} – {f['name']}, Farbe {col or '?'}. {grund}." + ("" if generic else " Welche Sorte steckt darin?")
    from urllib.parse import quote
    link = einstellungen().get("fach_link") or "/schichtlohn-app"
    trenn = "&" if "?" in link else "?"
    knoepfe = [] if generic else [{"action": "URI", "title": n[:45], "uri": f"{link}{trenn}sl_fach={quote(eid)}&sl_sorte={quote(u)}"}
                                   for _, u, n in kand[:3]]
    knoepfe.append({"action": "URI", "title": "In SchichtLohn öffnen", "uri": f"{link}{trenn}sl_fach={quote(eid)}"})
    erg = {"status": "offen", "meldung": text, "knoepfe": knoepfe}
    if melden_:
        handy_meldung("Filament: Fach nicht zugeordnet", text, aktionen=knoepfe, tag="filament_" + eid[7:])
        FACH_GEMELDET[eid] = (fid, col)
    return erg


def _meldung_weg(eid):
    """Offene Fach-Meldung auf dem Handy entfernen (Fach inzwischen zugeordnet oder geleert)."""
    FACH_GEMELDET.pop(eid, None)
    h = einstellungen()["ha"]
    roh = h.get("notify") or ""
    ziele = [z.strip() for z in (roh if isinstance(roh, list) else str(roh).split(",")) if z.strip().startswith("notify.")]
    url, token = ha_cfg()
    if not (url and token):
        return
    for ziel in ziele:
        im_hintergrund(ha_anfrage, "/api/services/notify/" + ziel[7:], {"message": "clear_notification", "data": {"tag": "filament_" + eid[7:]}})
    if not ziele:
        im_hintergrund(ha_anfrage, "/api/services/persistent_notification/dismiss", {"notification_id": "filament_" + eid[7:]})


def faecher_durchlauf(jetzt=None):
    jetzt = time.time() if jetzt is None else jetzt
    an = einstellungen().get("fach_meldung", True)
    faecher = faecher_sammeln()
    for eid, f in faecher.items():
        nutzbar = f["fid"] and not f["leer"] and str(f["state"]) not in ("unavailable", "unknown", "")
        if str(f["state"]) in ("unavailable", "unknown"):
            continue  # Drucker aus/an: Stand behalten, nichts melden
        sig = (f["fid"], f["col"]) if nutzbar else None
        st = FACH_STAND.get(eid)
        if st is None:  # erster Blick nach dem Start: nur merken
            FACH_STAND[eid] = {"sig": sig, "neu": None, "seit": jetzt}
            continue
        if sig == st["sig"]:
            st["neu"] = None
            continue
        if st["neu"] != sig:
            st["neu"], st["seit"] = sig, jetzt
            continue
        if jetzt - st["seit"] < FACH_RUHE:
            continue
        st["sig"], st["neu"] = sig, None
        if eid in FACH_GEMELDET:
            _meldung_weg(eid)
        if sig and an:
            try:
                fach_pruefen(eid, f)
            except Exception as ex:
                print("Fach prüfen:", eid, ex, flush=True)
    # offene Meldungen aufräumen, sobald das Fach im Lager zugeordnet ist (z. B. über den Knopf)
    for eid in list(FACH_GEMELDET):
        f = faecher.get(eid)
        if not f or fach_pruefen(eid, f, melden_=False)["status"] != "offen":
            _meldung_weg(eid)


HA_IDS_KEY = "_ha_ids_uebernommen"


def ha_ids_uebernehmen(erzwingen=False):
    """Einmalig: Bambu-IDs und gelernte AMS-Farben aus der alten HA-Liste todo.filament in das Server-Lager holen.
    Füllt nur, was auf dem Server fehlt (gleiche Sorte über uid, sonst über den Namen); Bestand, Preise usw. bleiben."""
    fertig, _ = daten_lesen(HA_IDS_KEY)
    if fertig and not erzwingen:
        return fertig
    url, token = ha_cfg()
    if not (url and token):
        return None
    antwort = ha_anfrage("/api/services/todo/get_items?return_response", {"entity_id": ENT}, timeout=30)
    ha_items = ((antwort or {}).get("service_response") or {}).get(ENT, {}).get("items") or []
    nach_uid = {it.get("uid"): it for it in ha_items}
    nach_name = {}
    for it in ha_items:
        nach_name.setdefault(str(it.get("summary") or "").strip().lower(), it)
    ids = farben = 0
    for it in liste_lesen(ENT):
        d = _desc(it)
        if not d.get("material"):
            continue
        h = nach_uid.get(it["uid"]) or nach_name.get(str(it["summary"] or "").strip().lower())
        if not h:
            continue
        hd = _desc(h)
        neu = dict(d)
        if not str(d.get("bambu_id") or "").strip() and str(hd.get("bambu_id") or "").strip():
            neu["bambu_id"] = str(hd["bambu_id"]).strip()
            ids += 1
        alt_f = [x.lower() for x in (d.get("ams_farben") or []) if isinstance(x, str)]
        dazu = [x.lower() for x in (hd.get("ams_farben") or []) if isinstance(x, str) and x.lower() not in alt_f]
        if dazu and (neu.get("bambu_id") or "") == (hd.get("bambu_id") or ""):
            neu["ams_farben"] = alt_f + dazu
            farben += 1
        if neu != d:
            liste_aendern(ENT, "update_item", {"item": it["uid"], "description": json.dumps(neu, ensure_ascii=False)})
    erg = {"zeit": time.strftime("%Y-%m-%dT%H:%M:%S"), "bambu_ids": ids, "ams_farben": farben, "ha_eintraege": len(ha_items)}
    daten_schreiben(HA_IDS_KEY, erg)
    print(f"Aus der HA-Liste übernommen: {ids} Bambu-IDs, {farben}× AMS-Farben", flush=True)
    return erg


def faecher_schleife():
    time.sleep(40)
    try:
        ha_ids_uebernehmen()
    except Exception as ex:
        print("Bambu-IDs aus HA:", ex, flush=True)
    while True:
        try:
            faecher_durchlauf()
        except Exception as ex:
            print("Fächer:", ex, flush=True)
        time.sleep(FACH_TAKT)


# ---------------------------------------------------------------- Waage: Antworten wie Home Assistant

AMS_RE = re.compile(r"_(ams_\d+_slot_\d+|externalspool\d*_externe_spule)$")
FEUCHTE_RE = re.compile(r"_ams_\d+_(luftfeuchtigkeit|index_der_luftfeuchtigkeit)(_\d+)?$")
STATUS_RE = re.compile(r"^sensor\.[^_]+_[^_]+_druckstatus$")


def ams_vorlage():
    """Ergebnis der AMS-Vorlage der Waage (pi_system.AMS_VORLAGE), berechnet aus den eigenen Zuständen."""
    slots, drucker = [], []
    for z in zustaende_liste():
        e, a = z["entity_id"], z["attributes"]
        if e.startswith("sensor.") and (AMS_RE.search(e) or FEUCHTE_RE.search(e)):
            slots.append({"e": e, "s": z["state"], "name": a.get("name"), "color": a.get("color"), "fid": a.get("filament_id"),
                          "empty": a.get("empty"), "active": a.get("active"), "remain": a.get("remain"), "tag": a.get("tag_uid"),
                          "type": a.get("type")})
        if STATUS_RE.match(e):
            drucker.append({"p": e[7:-12], "name": a.get("drucker_name") or "", "online": z["state"] not in ("unavailable", "unknown", "offline")})
    return {"slots": slots, "drucker": drucker, "abbuchung": "on" if einstellungen().get("abbuchung", True) and BAMBU.drucker else "off"}


def ha_dienst(domain, service, b):
    """POST /api/services/<domain>/<service> – Todo-Listen beantwortet der Server selbst, alles andere geht an HA."""
    if domain == "todo":
        ents = b.get("entity_id") or (b.get("target") or {}).get("entity_id")
        ents = ents if isinstance(ents, list) else [ents]
        if service == "get_items":
            st = b.get("status")
            st = st if isinstance(st, list) else ([st] if st else None)
            antwort = {}
            for e in ents:
                items = [{k: v for k, v in it.items()} for it in liste_lesen(e) if not st or it["status"] in st]
                antwort[e] = {"items": items}
            return {"changed_states": [], "service_response": antwort}
        for e in ents:
            daten = {k: v for k, v in b.items() if k not in ("entity_id", "target")}
            liste_aendern(e, service, daten)
        return []
    return ha_anfrage(f"/api/services/{domain}/{service}", b)


class Handler(BaseHTTPRequestHandler):
    server_version = "SchichtLohn-Server/" + VERSION
    protocol_version = "HTTP/1.1"

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Token, Authorization")
        self.send_header("Access-Control-Allow-Private-Network", "true")
        self.send_header("Access-Control-Max-Age", "86400")

    def _json(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self._cors()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _datei(self, pfad, typ):
        if not pfad:
            raise Fehler(404, "Filament-Datenbank fehlt – in SchichtLohn unter Einstellungen → SchichtLohn-Server aktualisieren")
        st = os.stat(pfad)
        etag = '"%x-%x"' % (int(st.st_mtime), st.st_size)
        if self.headers.get("If-None-Match") == etag:
            self.send_response(304)
            self._cors()
            self.send_header("ETag", etag)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        with open(pfad, "rb") as f:
            body = f.read()
        self.send_response(200)
        self._cors()
        self.send_header("Content-Type", typ)
        self.send_header("Cache-Control", "no-cache")
        self.send_header("ETag", etag)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _rumpf(self, grenze):
        if "chunked" in (self.headers.get("Transfer-Encoding") or "").lower():
            teile, summe = [], 0
            while True:
                zeile = self.rfile.readline(1024).strip()
                groesse = int(zeile.split(b";")[0] or b"0", 16)
                if groesse == 0:
                    self.rfile.readline(1024)
                    break
                summe += groesse
                if summe > grenze:
                    raise Fehler(413, "Anfrage zu groß")
                teile.append(self.rfile.read(groesse))
                self.rfile.readline(1024)
            if not summe:
                raise Fehler(400, "Leere Anfrage")
            return b"".join(teile)
        n = int(self.headers.get("Content-Length") or 0)
        if n <= 0:
            raise Fehler(400, "Leere Anfrage")
        if n > grenze:
            raise Fehler(413, "Anfrage zu groß")
        return self.rfile.read(n)

    def _json_rumpf(self):
        try:
            return json.loads(self._rumpf(MAX_JSON).decode("utf-8"))
        except ValueError:
            raise Fehler(400, "Ungültiges JSON")

    def _pfad(self):
        u = urlparse(self.path)
        return u.path.rstrip("/") or "/", parse_qs(u.query)

    def _darf(self, q):
        tok = token_aktuell()
        if not tok:
            return True
        t = self.headers.get("X-Token") or (q.get("token") or [""])[0]
        a = self.headers.get("Authorization") or ""
        if a.lower().startswith("bearer "):
            t = t or a[7:].strip()
        import hmac
        return hmac.compare_digest(str(t or ""), tok)

    def _senden(self, code, body, typ, cache="no-cache"):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self._cors()
        self.send_header("Content-Type", typ)
        self.send_header("Cache-Control", cache)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _web(self, methode):
        """App und Bibliotheken; → True, wenn beantwortet"""
        roh = urlparse(self.path)
        if methode != "GET":
            return False
        if roh.path == "/app":
            self.send_response(301)
            self.send_header("Location", "/app/")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return True
        basis = (self.headers.get("X-Ingress-Path") or "").rstrip("/")
        if roh.path == "/app/" or roh.path == "/app/index.html":
            html = web.app_html(WEB, basis)
            if html is None:
                raise Fehler(404, "App fehlt – in SchichtLohn unter Einstellungen → SchichtLohn-Server „App aktualisieren“")
            self._senden(200, html, "text/html; charset=utf-8")
            return True
        if roh.path.startswith("/hersteller/"):
            # Herstellerlogos aus Home Assistant (/config/www/hersteller, nur lesend eingebunden) – damit die App
            # sie auch ohne Home Assistant zeigt (z. B. über Tailscale)
            from urllib.parse import unquote
            name = os.path.basename(unquote(roh.path[len("/hersteller/"):]))
            if re.fullmatch(r"[a-z0-9][a-z0-9-]*\.(png|webp|jpg|svg)", name):
                for d in HERSTELLER_ORDNER:
                    p = os.path.join(d, name)
                    if os.path.isfile(p):
                        with open(p, "rb") as f:
                            self._senden(200, f.read(), web.typ_fuer(p), "max-age=3600")
                        return True
            raise Fehler(404, "Kein Logo")
        if roh.path.startswith("/app/"):
            p = web.app_datei(WEB, roh.path[5:])
            if not p:
                raise Fehler(404, "Unbekannte Datei")
            with open(p, "rb") as f:
                self._senden(200, f.read(), web.typ_fuer(p))
            return True
        art, _, rest = roh.path.lstrip("/").partition("/")
        if art in web.QUELLEN and rest:
            if roh.query:
                rest += "?" + roh.query
            try:
                r = web.vendor(WEB, art, rest)
            except Exception as e:
                raise Fehler(502, "Nicht im Zwischenspeicher und ohne Internet nicht ladbar: " + str(e))
            if not r:
                raise Fehler(404, "Unbekannt")
            body = r[0]
            if basis and any(t in r[1] for t in ("javascript", "css")):
                body = re.sub(rb'(["\'(])/(npm|cdnjs|gfonts|gstatic)/', lambda m: m.group(1) + basis.encode() + b"/" + m.group(2) + b"/", body)
            self._senden(200, body, r[1], "public, max-age=604800")
            return True
        return False

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _route(self, methode):
        pfad, q = self._pfad()
        if pfad in ("/", "/status") and methode == "GET":
            return self._json(200, {"ok": True, "dienst": "schichtlohn-server", "version": VERSION, "datenbank": True,
                                    "etikett": OCR_AN, "lernen": os.path.exists(MERKMAL_MODELL), "filamentdb": fdb_info().get("stand"), "lesemodell": ("standard" if os.environ.get("LESEMODELL") == "standard" or not os.path.exists(os.path.join(MODELLE, "ocr_rec.onnx")) else "genau" if os.environ.get("LESEMODELL") == "genau" else "auto (Foto schnell, Ausschnitt genau)"), "token": bool(token_aktuell()), "token_quelle": "umgebung" if TOKEN_UMGEBUNG else ("app" if token_aktuell() else ""), "zugang": self._darf(q), "app": web.app_info(WEB).get("vorhanden", False), "drucker": len(BAMBU.drucker), "ha_app": HA_APP})
        if pfad == "/lesen" and methode == "POST":
            t0 = time.time()
            print(f"Foto empfangen ({self.headers.get('Content-Length') or self.headers.get('Transfer-Encoding') or '?'} Byte) …", flush=True)
            daten = self._rumpf(MAX_BILD)
            try:
                r = bild_lesen(daten, ausschnitt=(q.get("ausschnitt") or ["0"])[0] == "1")
            except Exception as e:
                raise Fehler(400, "Das Bild ließ sich nicht auswerten: " + str(e))
            r["ms"] = int((time.time() - t0) * 1000)
            return self._json(200, r)
        if pfad == "/mcp" or pfad.startswith("/mcp/"):
            return self._mcp(methode, pfad, q)
        if pfad == "/filamentdb.json" and methode == "GET":
            return self._datei(fdb_pfad(), "application/json; charset=utf-8")
        if self._web(methode):
            return
        if pfad == "/api" and methode == "GET":
            return self._json(200, {"message": "API running."})
        if not pfad.startswith("/api/"):
            raise Fehler(404, "Unbekannter Pfad")
        if not self._darf(q):
            raise Fehler(401, "Falscher oder fehlender Schlüssel")
        teile = [unquote(x) for x in pfad.split("/")[2:]]
        if teile == ["rollen"] and methode == "GET":
            return self._json(200, {"rollen": rollen_liste()})
        if teile == ["rolle"] and methode == "POST":
            b = self._json_rumpf()
            dr, ort, aktion = str(b.get("drucker") or ""), str(b.get("ort") or ""), str(b.get("aktion") or "")
            if aktion not in ("voll", "gramm", "entfernen") or not dr or not ort:
                raise Fehler(400, "drucker, ort und aktion (voll, gramm, entfernen) fehlen")
            ziel = next((r for r in rollen_liste() if r["drucker"] == dr and r["ort"] == ort), None)
            if not ziel or not ziel.get("uid"):
                raise Fehler(404, "Diesem Fach ist keine Sorte mit Bestand zugeordnet – erst in SchichtLohn zuordnen")
            it = next(i for i in liste_lesen(ENT) if i["uid"] == ziel["uid"])
            d = _desc(it)
            if aktion == "gramm":
                try:
                    g = float(str(b.get("g")).replace(",", "."))
                except (TypeError, ValueError):
                    raise Fehler(400, "g muss eine Zahl sein")
                if not 0 <= g <= 20000:
                    raise Fehler(400, "g zwischen 0 und 20000")
            else:
                g = None
            neu = rolle_setzen(d, dr, ort, aktion, g, str(b.get("quelle") or ""))
            # Fach ist jetzt dieser Sorte zugeordnet: bei anderen Sorten den Eintrag für dieses Fach entfernen
            key = fach_key(dr, ort)
            for i2 in liste_lesen(ENT):
                if i2["uid"] == it["uid"]:
                    continue
                d2 = _desc(i2)
                if isinstance(d2.get("faecher"), dict) and key in d2["faecher"]:
                    d2 = dict(d2, faecher={k: v for k, v in d2["faecher"].items() if k != key})
                    liste_aendern(ENT, "update_item", {"item": i2["uid"], "description": json.dumps(d2, ensure_ascii=False)})
            liste_aendern(ENT, "update_item", {"item": it["uid"], "description": json.dumps(neu, ensure_ascii=False)})
            return self._json(200, {"ok": True, "sorte": it["summary"], "rolle": (neu.get("faecher") or {}).get(key), "bestand_g": abbuchen_rechnen(neu, 0)[1]})
        if teile == ["zugang"] and methode == "GET":
            w, _ = daten_lesen(ZUGANG_KEY)
            tok = token_aktuell()
            return self._json(200, {"quelle": "umgebung" if TOKEN_UMGEBUNG else ("app" if tok else ""), "aktiv": bool(tok),
                                    "seit": (w or {}).get("seit") if isinstance(w, dict) and not TOKEN_UMGEBUNG and tok else None,
                                    "maske": (tok[:4] + "-••••-••••-••••") if tok and not TOKEN_UMGEBUNG else "",
                                    "token": tok if tok and not TOKEN_UMGEBUNG and (q.get("voll") or [""])[0] == "1" else None})
        if teile == ["zugang"] and methode == "POST":
            if TOKEN_UMGEBUNG:
                raise Fehler(409, "Der Schlüssel ist in der Konfiguration eingetragen (Home Assistant: Feld token, sonst TOKEN in docker-compose) und wird dort geändert")
            b = self._json_rumpf()
            aktion = b.get("aktion")
            if aktion == "erzeugen":
                neu = zugang_erzeugen()
            elif aktion == "setzen":
                neu = str(b.get("token") or "").strip()
                if len(neu) < 8 or len(neu) > 200 or not re.fullmatch(r"[\w.\-~+=]+", neu):
                    raise Fehler(400, "Der Schlüssel braucht mindestens 8 Zeichen (Buchstaben, Ziffern, - . _ ~ + =)")
            elif aktion == "aus":
                neu = ""
            else:
                raise Fehler(400, "aktion: erzeugen, setzen oder aus")
            zugang_setzen(neu)
            print("Zugang: Schlüssel " + ("geändert" if neu else "ausgeschaltet"), flush=True)
            return self._json(200, {"ok": True, "aktiv": bool(neu), "token": neu or None})
        if teile == ["mcp"] and methode in ("GET", "POST"):
            neu = methode == "POST" and bool(self._json_rumpf().get("neu"))
            return self._json(200, {"pfad": "/mcp/" + mcp_schluessel(neu), "neu": neu,
                                    "werkzeuge": [w[0] for w in mcp_mod.WERKZEUGE]})
        if teile[0] == "listen" and len(teile) == 2:
            name = teile[1]
            if methode == "GET":
                return self._json(200, {"items": liste_lesen(name), "rev": rev(name)})
            if methode == "POST":
                b = self._json_rumpf()
                try:
                    return self._json(200, liste_aendern(name, b.get("service"), b.get("data") or {}))
                except KeyError as e:
                    raise Fehler(404, str(e).strip("'"))
                except ValueError as e:
                    raise Fehler(400, str(e))
            if methode == "PUT":
                b = self._json_rumpf()
                if not isinstance(b.get("items"), list):
                    raise Fehler(400, "items fehlt")
                return self._json(200, liste_ersetzen(name, b["items"]))
        if teile[0] == "produktbild" and len(teile) == 1:
            # Vorschaubild für eine Rechnungsposition (Amazon/AliExpress über die Artikel-ID, Bambu über den Namen)
            g = lambda x: (q.get(x) or [""])[0][:300]
            if methode == "GET":
                bild = BILDER.holen(g("quelle"), g("id"), g("n"), g("v"))
                if not bild:
                    return self._senden(404, b"", "image/jpeg", "private, max-age=3600")
                return self._senden(200, bild, "image/jpeg", "private, max-age=2592000")
            if methode == "PUT":
                b = self._json_rumpf()
                try:
                    bild = BILDER.eigenes(str(b.get("quelle") or ""), str(b.get("id") or ""), str(b.get("n") or ""),
                                          str(b.get("v") or ""), b.get("url"))
                except ValueError as e:
                    raise Fehler(400, str(e))
                return self._json(200, {"ok": True, "bild": bool(bild)})
        if teile[0] == "daten" and len(teile) == 2:
            k = teile[1]
            if k.startswith("_"):
                raise Fehler(403, "Geschützter Schlüssel")
            if methode == "GET":
                w, t = daten_lesen(k)
                if t is None:
                    return self._json(404, {"fehler": "Nicht vorhanden"})
                return self._json(200, {"wert": w, "geaendert": t, "rev": rev("daten:" + k)})
            if methode == "PUT":
                b = self._json_rumpf()
                return self._json(200, {"rev": daten_schreiben(k, b.get("wert"), str(b.get("quelle") or ""))})
        if teile == ["abdruck"] and methode == "POST":
            b = self._json_rumpf()
            if not b.get("uid") or not b.get("vid"):
                raise Fehler(400, "uid und vid fehlen")
            return self._json(200, abdruck_speichern(str(b["uid"]), str(b["vid"])))
        if teile == ["filamentdb"] and methode == "GET":
            return self._json(200, dict(fdb_info(), auto=AUTO))
        if teile == ["filamentdb", "aktualisieren"] and methode == "POST":
            return self._json(200, fdb_aktualisieren())
        if teile == ["werte_ergaenzen"] and methode == "POST":
            b = self._json_rumpf() if int(self.headers.get("Content-Length") or 0) else {}
            return self._json(200, werte_ergaenzen(bool(b.get("vorschau")), bool(b.get("neu_laden"))))
        if teile == ["sorten"] and methode == "GET":
            return self._json(200, {"sorten": sorten()})
        if teile == ["sicherung"] and methode == "GET":
            return self._json(200, sicherung())
        if teile == ["ereignisse"] and methode == "GET":
            return self._sse()
        # --- wie Home Assistant (für die Waage und die Lager-Ansicht)
        if teile[0] == "services" and len(teile) == 3 and methode == "POST":
            b = self._json_rumpf() if int(self.headers.get("Content-Length") or 0) else {}
            try:
                return self._json(200, ha_dienst(teile[1], teile[2], b))
            except KeyError as e:
                raise Fehler(404, str(e).strip("'"))
            except ValueError as e:
                raise Fehler(400, str(e))
        if teile[0] == "states":
            if len(teile) == 1 and methode == "GET":
                return self._json(200, zustaende_liste())
            if len(teile) == 2 and methode == "GET":
                z = next((z for z in zustaende_liste() if z["entity_id"] == teile[1]), None)
                if not z:
                    raise Fehler(404, "Entity not found.")
                return self._json(200, z)
            if len(teile) == 2 and methode == "POST":
                b = self._json_rumpf()
                z = zustand_setzen(teile[1], str(b.get("state", "")), b.get("attributes") or {}, "api")
                if all(ha_cfg()):
                    im_hintergrund(ha_anfrage, "/api/states/" + teile[1], b)
                return self._json(201, z)
        if teile[0] == "events" and len(teile) == 2 and methode == "POST":
            b = self._json_rumpf() if int(self.headers.get("Content-Length") or 0) else {}
            melden({"typ": "ereignis", "name": teile[1], "daten": b})
            if all(ha_cfg()):
                im_hintergrund(ha_anfrage, "/api/events/" + teile[1], b)
            return self._json(200, {"message": f"Event {teile[1]} fired."})
        if teile == ["template"] and methode == "POST":
            t = str(self._json_rumpf().get("template") or "")
            if "_ams_" in t and "states.sensor" in t and (BAMBU.drucker or not all(ha_cfg())):
                return self._senden(200, json.dumps(ams_vorlage(), ensure_ascii=False), "text/plain; charset=utf-8", "no-store")
            if all(ha_cfg()):
                return self._senden(200, ha_anfrage("/api/template", {"template": t}, roh=True), "text/plain; charset=utf-8", "no-store")
            raise Fehler(400, "Vorlagen gehen nur mit eingetragenem Home Assistant")
        # --- Einstellungen, Drucker, App
        if teile == ["einstellungen"]:
            if methode == "GET":
                return self._json(200, einstellungen_maskiert())
            if methode == "PUT":
                return self._json(200, einstellungen_setzen(self._json_rumpf()))
        if teile == ["preise"] and methode == "GET":
            w, _ = daten_lesen(PREISE_KEY)
            return self._json(200, dict(w if isinstance(w, dict) else {}, laeuft=PREISE_STAND["laeuft"]))
        if teile == ["preise", "suche"] and methode == "GET":
            cfg = einstellungen().get("preise") or {}
            an = [k for k, f in (("ebay", ("id", "secret")), ("ali", ("key", "secret"))) if all((cfg.get(k) or {}).get(x) for x in f)]
            erg = preise_mod.suchen(cfg, (q.get("q") or [""])[0]) if an else {"ebay": [], "ali": [], "fehler": []}
            return self._json(200, dict(erg, dienste=an))
        if teile == ["preise", "protokoll"] and methode == "GET":
            w, _ = daten_lesen(PROTOKOLL_KEY)
            return self._json(200, {"laeufe": w if isinstance(w, list) else []})
        if teile == ["preise", "abrufen"] and methode == "POST":
            im_hintergrund(preise_abrufen, "von Hand")
            return self._json(200, {"ok": True, "laeuft": True})
        if teile[0] == "waage" and len(teile) == 2:
            return self._json(200, waage_weiter(teile[1], methode, self._json_rumpf() if methode == "POST" else None))
        if teile == ["telegram", "chat"] and methode == "POST":
            b = self._json_rumpf() if int(self.headers.get("Content-Length") or 0) else {}
            if b.get("token") and b["token"] != MASKE:
                einstellungen_setzen({"telegram": {"token": re.sub(r"\s+", "", str(b["token"]))}})
            gefunden = telegram_chat_finden()
            einstellungen_setzen({"telegram": {"chat": gefunden["chat"], "chat_name": gefunden["name"]}})
            return self._json(200, gefunden)
        if teile == ["telegram", "test"] and methode == "POST":
            # Mit Kamerabild des ersten Druckers, den Home Assistant kennt – so sieht man gleich, ob Bilder ankommen
            foto = next((f for f in (kamera_foto(pre) for pre in list(HA_DRUCKER)[:3]) if f), None)
            if not telegram_senden("SchichtLohn – Test", "Telegram-Meldungen funktionieren. Jede Schicht zählt."
                                   + (" Das Bild kommt aus der Druckerkamera." if foto else ""), "", foto):
                raise Fehler(400, "Telegram ist noch nicht vollständig eingerichtet (Token und Chat fehlen)")
            return self._json(200, {"ok": True})
        if teile == ["ha", "notify", "test"] and methode == "POST":
            if not all(ha_cfg()):
                raise Fehler(503, "Home Assistant ist im Server nicht verbunden")
            roh = einstellungen()["ha"].get("notify") or ""
            ziele = [z.strip() for z in (roh if isinstance(roh, list) else str(roh).split(",")) if z.strip().startswith("notify.")]
            titel, text = "SchichtLohn – Test", "Benachrichtigungen funktionieren. Jede Schicht zählt."
            ok, fehler = [], []
            if not ziele:
                ha_anfrage("/api/services/persistent_notification/create",
                           {"title": titel, "message": text, "notification_id": "schichtlohn_test"})
                return self._json(200, {"ok": ["Home Assistant (Mitteilungen)"], "fehler": []})
            for ziel in ziele:
                try:
                    ha_anfrage("/api/services/notify/" + ziel[7:], {"title": titel, "message": text})
                    ok.append(ziel)
                except Exception as ex:
                    fehler.append({"ziel": ziel, "fehler": str(ex)})
            return self._json(200, {"ok": ok, "fehler": fehler})
        if teile == ["ha", "notify"] and methode == "GET":
            if not all(ha_cfg()):
                return self._json(200, {"dienste": [], "verbunden": False})
            try:
                dienste = []
                for d in ha_anfrage("/api/services") or []:
                    if d.get("domain") == "notify":
                        for name in (d.get("services") or {}):
                            if name.startswith("mobile_app_"):
                                n = name[11:].replace("_", " ").title()
                                for alt, neu in (("Iphone", "iPhone"), ("Ipad", "iPad"), ("Macbook", "MacBook"), (" Von ", " von ")):
                                    n = n.replace(alt, neu)
                                dienste.append({"id": "notify." + name, "name": n})
                return self._json(200, {"dienste": sorted(dienste, key=lambda x: x["name"]), "verbunden": True})
            except Exception as ex:
                return self._json(200, {"dienste": [], "verbunden": False, "fehler": str(ex)})
        if teile == ["faecher", "ha_ids"] and methode == "POST":
            return self._json(200, ha_ids_uebernehmen(erzwingen=True) or {"fehler": "Home Assistant nicht erreichbar"})
        if teile == ["faecher"] and methode == "GET":
            # alle AMS-Fächer mit Prüfergebnis gegen das Lager (ohne Meldung)
            out = []
            for eid, f in sorted(faecher_sammeln().items()):
                erg = fach_pruefen(eid, f, melden_=False)
                out.append({"entity_id": eid, "drucker": f["drucker"], "ort": fach_ort(eid), "name": f["name"],
                            "filament_id": f["fid"], "farbe": f["col"], **erg})
            return self._json(200, {"faecher": out, "meldung_an": einstellungen().get("fach_meldung", True)})
        if teile == ["drucke"] and methode == "GET":
            w, _ = daten_lesen(DRUCKE_KEY)
            sp, _ = daten_lesen(SPEICHER_KEY)
            return self._json(200, {"drucke": w if isinstance(w, list) else [], "speicher": sp if isinstance(sp, dict) else {},
                                    "laeuft": SPEICHER_STAND["laeuft"], "archiv": archiv_info()})
        if teile == ["drucke", "import"] and methode == "POST":
            # Drucke aus einer anderen App übernehmen (z. B. Spooly): gleiche id ersetzt, sonst dazu
            b = self._json_rumpf()
            neu = [x for x in (b.get("drucke") or []) if isinstance(x, dict) and x.get("id")]
            return self._json(200, drucke_importieren(neu))
        if len(teile) >= 2 and teile[0] == "kamera" and methode == "GET":
            # Druckerkamera über Home Assistant: Einzelbild (…/<präfix>.jpg) oder Live-Bild (…/<präfix>/live, MJPEG)
            pre = re.sub(r"[^a-z0-9_]", "", teile[1].lower().removesuffix(".jpg"))
            if not pre:
                raise Fehler(400, "Drucker fehlt")
            if len(teile) == 3 and teile[2] == "live":
                return self._kamera_live(pre)
            bild = kamera_foto(pre)
            if not bild:
                return self._senden(404, b"", "image/jpeg", "no-store")
            return self._senden(200, bild, "image/jpeg" if bild[:1] == b"\xff" else "image/png", "no-store")
        if teile == ["drucke", "entfernen"] and methode == "POST":
            b = self._json_rumpf()
            ids, herkunft = set(b.get("ids") or []), str(b.get("herkunft") or "")
            if not ids and not herkunft:
                raise Fehler(400, "ids oder herkunft fehlt")
            with _db_lock:
                alt, _ = daten_lesen(DRUCKE_KEY)
                alt = [x for x in (alt if isinstance(alt, list) else []) if isinstance(x, dict)]
                neu = [x for x in alt if x.get("id") not in ids and not (herkunft and x.get("herkunft") == herkunft)]
                daten_schreiben(DRUCKE_KEY, neu)
            melden({"typ": "drucke"})
            return self._json(200, {"ok": True, "entfernt": len(alt) - len(neu), "gesamt": len(neu)})
        if teile == ["drucke", "speicher"] and methode == "POST":
            im_hintergrund(speicher_abrufen, "von Hand")
            return self._json(200, {"ok": True, "laeuft": True})
        if teile == ["drucker", "fach"] and methode == "POST":
            return self._json(200, fach_belegen(self._json_rumpf()))
        if teile == ["drucke", "senden", "pruefen"] and methode == "POST":
            k = self._json_rumpf()
            return self._json(200, senden_pruefen(k.get("serial"), k.get("name")))
        if teile == ["drucke", "senden"] and methode == "POST":
            return self._json(200, senden(self._json_rumpf()))
        if teile == ["drucke", "archiv"] and methode == "GET":
            return self._json(200, {"dateien": archiv_liste(), "archiv": archiv_info()})
        if teile == ["drucke", "datei", "loeschen"] and methode == "POST":
            k = self._json_rumpf()
            serial = re.sub(r"[^A-Z0-9]", "", str(k.get("serial") or "").upper())
            name = os.path.basename(str(k.get("name") or ""))
            pf = os.path.join(DRUCKDATEIEN, serial, name)
            if not serial or not name.lower().endswith(".3mf") or not os.path.exists(pf):
                raise Fehler(404, "Druckdatei nicht gesichert")
            os.remove(pf)
            return self._json(200, {"ok": True, "archiv": archiv_info()})
        if len(teile) == 4 and teile[:2] == ["drucke", "datei"] and methode == "GET":
            serial = re.sub(r"[^A-Z0-9]", "", teile[2].upper())
            name = os.path.basename(unquote(teile[3]))
            pf = os.path.join(DRUCKDATEIEN, serial, name)
            if not serial or not name.lower().endswith(".3mf") or not os.path.exists(pf):
                raise Fehler(404, "Druckdatei nicht gesichert")
            with open(pf, "rb") as f:
                daten = f.read()
            self.send_response(200)
            self._cors()
            self.send_header("Content-Type", "application/vnd.ms-package.3dmanufacturing-3dmodel+xml")
            self.send_header("Content-Disposition", "attachment; filename*=UTF-8''" + quote(name))
            self.send_header("Content-Length", str(len(daten)))
            self.end_headers()
            self.wfile.write(daten)
            return
        if len(teile) == 3 and teile[:2] == ["drucke", "bild"] and methode == "GET":
            bid = re.sub(r"[^0-9a-f]", "", teile[2])[:16]
            pf = os.path.join(DRUCKBILDER, bid + ".png")
            if not bid or not os.path.exists(pf):
                return self._senden(404, b"", "image/png", "private, max-age=600")
            with open(pf, "rb") as f:
                return self._senden(200, f.read(), "image/png", "private, max-age=2592000")
        if teile == ["drucker"] and methode == "GET":
            return self._json(200, {"drucker": BAMBU.liste(), "mqtt": drucker_mod.mqtt is not None})
        if teile == ["drucker", "lan"] and methode == "POST":
            # Heimnetz zusätzlich zur Cloud: Druckerspeicher prüfen oder die IP suchen (für die genaue Abbuchung aus der Druckdatei)
            b = self._json_rumpf()
            serial = str(b.get("serial") or "").strip().upper()
            alt = next((d for d in einstellungen()["drucker"] if str(d.get("serial") or "").upper() == serial), {}) if serial else {}
            code = str(b.get("code") or "").strip()
            if not code or code == MASKE:
                code = alt.get("code") or ""
            if not code:
                raise Fehler(400, "Zugangscode fehlt – am Drucker unter Netzwerk ablesen")
            ip = str(b.get("ip") or "").strip()
            if ip and not b.get("suchen"):
                ok, text = drucker_mod.lan_pruefen(ip, code)
                return self._json(200, {"ok": ok, "ip": ip if ok else "", "text": text})
            ip, text = drucker_mod.lan_suchen(code, lan_netze(ip, self.headers.get("X-Forwarded-For") or self.client_address[0]))
            return self._json(200, {"ok": bool(ip), "ip": ip, "text": text})
        if teile == ["drucker", "neu_starten"] and methode == "POST":
            BAMBU.neu_starten()
            return self._json(200, {"ok": True})
        if teile == ["cloud", "zugang"] and methode == "GET":
            # Bambu-Anmeldung für die App auf diesem Server (einmal anmelden, alle Geräte verbunden)
            c = einstellungen()["cloud"]
            if not c.get("token"):
                return self._json(200, {})
            return self._json(200, {"token": c["token"], "region": c.get("region") or "global", "konto": c.get("konto") or ""})
        if teile == ["cloud", "geraete"] and methode == "POST":
            b = self._json_rumpf() if int(self.headers.get("Content-Length") or 0) else {}
            c = einstellungen()["cloud"]
            token = b.get("token") or c.get("token")
            region = b.get("region") or c.get("region") or "global"
            if not token:
                raise Fehler(400, "Nicht bei der Bambu-Cloud angemeldet")
            if b.get("token"):
                e = einstellungen()
                e["cloud"] = {"token": token, "region": region, "konto": b.get("konto") or ""}
                daten_schreiben(EINST_KEY, e)
                if any(d.get("modus") == "cloud" for d in e["drucker"]):
                    BAMBU.neu_starten()
            try:
                return self._json(200, {"geraete": drucker_mod.cloud_geraete(token, region)})
            except Exception as ex:
                raise Fehler(502, "Bambu-Cloud: " + str(ex))
        if teile == ["abdruecke"] and methode == "GET":
            return self._json(200, abdruecke_export())
        if teile == ["umzug"] and methode == "POST":
            b = self._json_rumpf()
            if not b.get("quelle"):
                raise Fehler(400, "Adresse des alten Servers fehlt")
            return self._json(200, umzug(str(b["quelle"]), str(b.get("token") or ""), bool(b.get("nur_daten"))))
        if teile == ["einrichten"] and methode == "POST":
            # Für den Installer: Preisquellen, Zugänge für eBay/AliExpress und Schlüssel in einem Schritt
            b = self._json_rumpf()
            out = {"ok": True}
            pq = b.get("preise") if isinstance(b.get("preise"), dict) else {}
            if "shop" in pq:
                cfg, _ = daten_lesen("cfg")
                cfg = cfg if isinstance(cfg, dict) else {}
                aus = set(cfg.get("fnAus") or [])
                (aus.discard if pq.get("shop") else aus.add)("preisliste")
                cfg["fnAus"] = sorted(aus)
                daten_schreiben("cfg", cfg, "einrichten")
            zug = {k: {kk: str(v) for kk, v in (pq.get(k) or {}).items() if kk in ("id", "secret", "key", "tracking") and v} for k in ("ebay", "ali")}
            if any(zug.values()):
                einstellungen_setzen({"preise": zug})
            if b.get("schluessel") == "erzeugen" and not TOKEN_UMGEBUNG and not token_aktuell():
                out["token"] = zugang_erzeugen()
                zugang_setzen(out["token"])
            out["mcp"] = "/mcp/" + mcp_schluessel()
            e = einstellungen()
            cfg, _ = daten_lesen("cfg")
            out["preise"] = {"shop": "preisliste" not in ((cfg or {}).get("fnAus") or []) if isinstance(cfg, dict) else True,
                             "ebay": bool(e["preise"]["ebay"].get("id") and e["preise"]["ebay"].get("secret")),
                             "ali": bool(e["preise"]["ali"].get("key") and e["preise"]["ali"].get("secret"))}
            return self._json(200, out)
        if teile == ["app"] and methode == "GET":
            return self._json(200, dict(web.app_info(WEB), auto=AUTO))
        if teile == ["app", "aktualisieren"] and methode == "POST":
            try:
                return self._json(200, web.aktualisieren(WEB))
            except RuntimeError as ex:
                raise Fehler(502, str(ex))
        raise Fehler(404, "Unbekannter Pfad")

    def _kamera_live(self, pre, dauer=600, takt=0.25):
        """Live-Bild als MJPEG: holt so schnell wie möglich Einzelbilder aus Home Assistant
        (der HA-Live-Strom der Bambu-Kameras startet oft zu langsam). Höchstens 10 Minuten am Stück."""
        url, token = ha_cfg()
        if not (url and token):
            raise Fehler(503, "Kamera braucht Home Assistant")
        erstes = kamera_foto(pre)
        if not erstes:
            raise Fehler(404, "Kein Kamerabild")
        self.send_response(200)
        self._cors()
        self.send_header("Content-Type", "multipart/x-mixed-replace;boundary=frame")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        self.close_connection = True
        ende, bild = time.time() + dauer, erstes
        try:
            while time.time() < ende:
                t0 = time.time()
                if bild:
                    art = b"image/jpeg" if bild[:1] == b"\xff" else b"image/png"
                    self.wfile.write(b"--frame\r\nContent-Type: " + art + b"\r\nContent-Length: " + str(len(bild)).encode() + b"\r\n\r\n" + bild + b"\r\n")
                    self.wfile.flush()
                warte = takt - (time.time() - t0)
                if warte > 0:
                    time.sleep(warte)
                bild = kamera_foto(pre)
                if not bild:
                    time.sleep(1)
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass

    def _sse(self):
        self.send_response(200)
        self._cors()
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Accel-Buffering", "no")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        self.close_connection = True
        q = queue.Queue(maxsize=200)
        with _hoerer_lock:
            _hoerer.add(q)
        try:
            self.wfile.write(b"retry: 3000\n: hallo\n\n")
            self.wfile.flush()
            while True:
                try:
                    ev = q.get(timeout=10)  # öfter ein Lebenszeichen, damit Tailscale & Co. die Verbindung nicht trennen
                    self.wfile.write(("data: " + json.dumps(ev, ensure_ascii=False) + "\n\n").encode("utf-8"))
                except queue.Empty:
                    self.wfile.write(b": ping\n\n")
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            with _hoerer_lock:
                _hoerer.discard(q)

    def _mcp(self, methode, pfad, q):
        import hmac
        teil = pfad[5:]
        ok = (bool(teil) and hmac.compare_digest(teil, mcp_schluessel())) or (bool(token_aktuell()) and self._darf(q))
        if not ok:
            raise Fehler(401, "MCP: Adresse mit Schlüssel verwenden (in SchichtLohn unter Einstellungen → SchichtLohn-Server)")
        if methode != "POST":  # kein Ereignisstrom: Antworten kommen direkt auf den POST
            self.send_response(405)
            self._cors()
            self.send_header("Allow", "POST")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        b = self._json_rumpf()
        if isinstance(b, list):
            antwort = [x for x in (mcp_mod.bearbeiten(m, VERSION) for m in b) if x is not None]
        else:
            antwort = mcp_mod.bearbeiten(b, VERSION)
        if not antwort:
            self.send_response(202)
            self._cors()
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        return self._json(200, antwort)

    def _los(self, methode):
        try:
            self._route(methode)
        except Fehler as e:
            self._json(e.code, {"fehler": str(e)})
        except Exception as e:
            self._json(500, {"fehler": "Serverfehler: " + str(e)})

    def do_GET(self):
        self._los("GET")

    def do_POST(self):
        self._los("POST")

    def do_PUT(self):
        self._los("PUT")

    def log_message(self, fmt, *args):
        if "/api/ereignisse" not in (self.path or ""):
            print("%s %s" % (self.address_string(), fmt % args), flush=True)


WEB = web.Ordner(os.path.dirname(os.path.abspath(DB_PFAD)))


class Server(ThreadingHTTPServer):
    daemon_threads = True


if __name__ == "__main__":
    db()
    print(f"SchichtLohn-Server {VERSION} · Port {PORT} · Datenbank {DB_PFAD} · Schlüssel {'an' if token_aktuell() else 'aus'}", flush=True)
    if OCR_AN:
        threading.Thread(target=ocr, daemon=True).start()  # Modell im Hintergrund laden
    # Als Hauptprozess im Container reagiert Python nicht von selbst auf „Stopp“ (SIGTERM) – sauber beenden
    import signal
    signal.signal(signal.SIGTERM, lambda *_: os._exit(0))
    BAMBU.neu_starten()
    if os.environ.get("AUTO_AKTUALISIEREN", "1") != "0":
        threading.Thread(target=auto_aktualisieren, daemon=True).start()
    threading.Thread(target=preise_auto, daemon=True).start()
    threading.Thread(target=speicher_auto, daemon=True).start()
    threading.Thread(target=ha_drucker_schleife, daemon=True).start()
    threading.Thread(target=faecher_schleife, daemon=True).start()
    Server(("0.0.0.0", PORT), Handler).serve_forever()
