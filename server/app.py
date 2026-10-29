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
  POST /api/waage/drucken             Etikett (1-Bit-Raster) an die Filamentwaage weiterreichen
  GET  /api/preise, POST …/abrufen    Preisvergleich eBay/AliExpress je Sorte (Schlüssel unter Einstellungen)
  GET  /api/drucker                   verbundene Bambu-Drucker (MQTT) mit AMS-Fächern

Wie Home Assistant (damit Waage und Lager-Ansicht unverändert arbeiten):
  POST /api/services/todo/get_items|update_item|add_item|remove_item
  GET/POST /api/states[/<entity>]     Drucker, AMS, Feuchte, Waage
  POST /api/template                  AMS-Vorlage der Waage (sonst an HA weitergereicht)
  POST /api/events/<name>             an HA weitergereicht, falls eingetragen

Mit der Umgebungsvariable TOKEN verlangt der Server bei /api/* den Schlüssel
(Kopfzeile X-Token oder ?token=…). Ohne TOKEN ist alles im Heimnetz offen.
"""
import io
import json
import os
import re
import queue
import sqlite3
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

import drucker as drucker_mod
import preise as preise_mod
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

VERSION = "3.2.6"
PORT = int(os.environ.get("PORT", "8093"))
DB_PFAD = os.environ.get("DB", "/daten/schichtlohn.db")
TOKEN = os.environ.get("TOKEN", "").strip()
MAX_BILD = 15 * 1024 * 1024
MAX_JSON = 32 * 1024 * 1024
MAX_SEITE = int(os.environ.get("MAX_SEITE", "1600"))
OCR_AN = os.environ.get("OCR", "1") != "0"
MERKMAL_MODELL = os.environ.get("MERKMAL_MODELL", "/app/modelle/mnv2_merkmale.onnx")
MODELLE = os.environ.get("MODELLE", os.path.dirname(MERKMAL_MODELL))

# ---------------------------------------------------------------- Datenbank

_db_lock = threading.Lock()


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
    r = db().execute("SELECT wert, geaendert FROM daten WHERE schluessel=?", (k,)).fetchone()
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
    w.setdefault("abbuchung", True)
    w.setdefault("fertig_meldung", True)
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
    for k in ("cloud", "ha"):
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
        alte = {d.get("id"): d for d in alt["drucker"]}
        liste = []
        for d in neu["drucker"]:
            d = {k: (v.strip() if isinstance(v, str) else v) for k, v in d.items()}
            d["id"] = d.get("id") or uuid.uuid4().hex[:8]
            if d.get("code") == MASKE:
                d["code"] = (alte.get(d["id"]) or {}).get("code", "")
            if d.get("serial"):
                d["serial"] = d["serial"].upper()
                if not d.get("modell"):
                    d["modell"] = drucker_mod.modell_aus_serie(d["serial"])
            liste.append(d)
        e["drucker"] = liste
    for k in ("cloud", "ha"):
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
        e["preise"] = pr
    if "fertig_meldung" in neu:
        e["fertig_meldung"] = bool(neu["fertig_meldung"])
    nur_extras = set(neu) <= {"fertig_meldung", "waage_url", "preise"}
    if "waage_url" in neu:
        u = str(neu["waage_url"] or "").strip().rstrip("/")[:120]
        if u and not re.match(r"^https?://", u):
            u = "http://" + u
        e["waage_url"] = u
    daten_schreiben(EINST_KEY, e)
    if isinstance(neu.get("preise"), dict):
        im_hintergrund(preise_abrufen)
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


def im_hintergrund(f, *a):
    def lauf():
        try:
            f(*a)
        except Exception as e:
            print("Hintergrund:", e, flush=True)
    threading.Thread(target=lauf, daemon=True).start()


PREISE_KEY = "_preisvergleich"
_preise_lock = threading.Lock()
PREISE_STAND = {"laeuft": False}


def preise_abrufen():
    """Aktuelle eBay- und AliExpress-Angebote für alle Sorten im Lager holen (täglich und nach dem Eintragen der Schlüssel)."""
    cfg = einstellungen().get("preise") or {}
    if not any(all((cfg.get(k) or {}).get(x) for x in f) for k, f in (("ebay", ("id", "secret")), ("ali", ("key", "secret")))):
        return None
    if not _preise_lock.acquire(blocking=False):
        return None
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
        werte, stat = preise_mod.abrufen(cfg, sorten, alt.get("werte"))
        neu = {"stand": time.strftime("%Y-%m-%d %H:%M"), "werte": werte, "ebay": stat["ebay"], "ali": stat["ali"],
               "sorten": len(sorten), "fehler": "; ".join(dict.fromkeys(stat["fehler"])) or None}
        daten_schreiben(PREISE_KEY, neu)
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
    pfade = {("drucken", "POST"): "/api/etikett/drucken", ("etikett", "GET"): "/api/etikett/einstellungen",
             ("zustand", "GET"): "/api/zustand"}
    pfad = pfade.get((was, methode))
    if not pfad:
        raise Fehler(404, "Unbekannt")
    if rumpf is not None:
        rumpf = {k: rumpf[k] for k in ("breite", "hoehe", "daten", "kopien") if k in rumpf}
    req = urllib.request.Request(basis + pfad, method=methode, headers={"Content-Type": "application/json"},
                                 data=json.dumps(rumpf).encode() if rumpf is not None else None)
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read().decode("utf-8") or "{}")
    except Exception as e:
        grund = getattr(e, "reason", None) or e
        raise Fehler(502, f"Waage unter {basis} nicht erreichbar ({getattr(grund, 'strerror', None) or grund}). "
                          "Läuft sie, und steht in ihrer config.toml unter [server] adresse = \"0.0.0.0\"?")


def handy_meldung(titel, text, bild=""):
    melden({"typ": "meldung", "titel": titel, "text": text})
    h = einstellungen()["ha"]
    roh = h.get("notify") or ""
    ziele = [z.strip() for z in (roh if isinstance(roh, list) else str(roh).split(",")) if z.strip().startswith("notify.")]
    url, token = ha_cfg()
    if not (url and token):
        return
    if ziele:
        for ziel in ziele:  # mehrere Handys: an jedes einzeln
            nachricht = {"title": titel, "message": text}
            if bild:  # iOS und Android zeigen das Bild in der Meldung
                nachricht["data"] = {"image": bild, "attachment": {"url": bild, "content-type": "png"}}
            im_hintergrund(ha_anfrage, "/api/services/notify/" + ziel[7:], nachricht)
    else:
        im_hintergrund(ha_anfrage, "/api/services/persistent_notification/create",
                       {"title": titel, "message": text, "notification_id": "filament_abbuchung"})


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
        dist = min(drucker_mod.farbabstand(h, col) if col else 0 for h in farben)
        if dist < abst:
            beste, abst = (it, d), dist
    if beste and abst <= 19200:
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


def fertig_melden(druckername, erg, kurz):
    """Eine Handymeldung zum Druckende: Auftrag, Drucker, Dauer, Verbrauch – mit Vorschaubild, wenn die Cloud eins hat."""
    aufgabe = (erg.get("aufgabe") or "").strip() or "Druckauftrag"
    titel = f"{erg['anlass']}: {aufgabe}"
    kopf = " · ".join(x for x in (druckername, _dauer(erg.get("dauer")),
                                  ("%d %%" % round(erg.get("anteil", 1) * 100)) if erg.get("anteil", 1) < 1 else "") if x)
    handy_meldung(titel, kopf + (". " + ". ".join(kurz) if kurz else ""), erg.get("bild") or "")


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
    for po in erg["posten"]:
        g = float(po.get("gramm") or 0)
        if g <= 0.05:
            continue
        treffer, grund = sorte_fuer(po.get("fid") or "", (po.get("col") or "").lower())
        if treffer:
            it, d = treffer
            vorher = abbuchen_rechnen(d, 0)[1]
            neu, bestand = abbuchen_rechnen(d, g)
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
                   "anlass": erg["anlass"], "quelle": "SchichtLohn-Server · " + erg.get("quelle", "")}
            liste_aendern(META, "add_item", {"item": f"{dt} · {druckername} · {_gram(g)} g · {it['summary']}",
                                             "description": json.dumps(log, ensure_ascii=False)})
            bericht.append(f"{it['summary']}: −{_gram(g)} g ({po.get('ort')}), Bestand {int(round(bestand))} g")
            kurz.append(f"{_gram(g)} g {it['summary']}, noch {int(round(bestand))} g")
        else:
            kurz.append(f"{_gram(g)} g nicht zugeordnet ({po.get('ort')})")
            offen.append(f"{po.get('ort')} ({_gram(g)} g): {grund}")
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
    anteil = erg.get("anteil", 1)
    text = f"{druckername}, {erg['anlass']}{' (%d %%)' % round(anteil * 100) if anteil < 1 else ''}. " + ". ".join(teile)
    print(text, flush=True)
    melden({"typ": "abbuchung", "drucker": druckername, "text": text})
    if fertig:
        fertig_melden(druckername, erg, kurz)
    else:
        handy_meldung("Filament abgebucht", text)
    if knapp:
        handy_meldung("Filament wird knapp", "; ".join(knapp) + ". Steht jetzt auf der Einkaufsliste in SchichtLohn.")


def abdruecke_export():
    import base64
    return [{"uid": u, "vek": base64.b64encode(b).decode(), "zeit": z} for u, b, z in db().execute("SELECT uid, vek, zeit FROM abdruecke")]


def umzug(quelle, token=""):
    """Alles von einem anderen SchichtLohn-Server (z. B. der Synology) übernehmen."""
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
        e = einstellungen()
        e["cloud"].update({"uid": c.get("uid")})
        daten_schreiben(EINST_KEY, e)

    def zustaende(self, dr, z):
        for eid, (s, a) in z.items():
            zustand_setzen(eid, s, a, "drucker")
        try:
            trocknen_pruefen(z)
        except Exception as ex:
            print("Trocknen:", ex, flush=True)

    def druckende(self, dr, erg):
        name = dr.d.get("name") or drucker_mod.MODELL_NAMEN.get(dr.d.get("modell") or "", dr.serial)
        druck_abbuchen(name, erg)

    def log(self, text):
        print(text, flush=True)


BAMBU = drucker_mod.Bambu(_Wirt())


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
        if not TOKEN:
            return True
        t = self.headers.get("X-Token") or (q.get("token") or [""])[0]
        a = self.headers.get("Authorization") or ""
        if a.lower().startswith("bearer "):
            t = t or a[7:].strip()
        return t == TOKEN

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
                                    "etikett": OCR_AN, "lernen": os.path.exists(MERKMAL_MODELL), "filamentdb": fdb_info().get("stand"), "lesemodell": ("standard" if os.environ.get("LESEMODELL") == "standard" or not os.path.exists(os.path.join(MODELLE, "ocr_rec.onnx")) else "genau" if os.environ.get("LESEMODELL") == "genau" else "auto (Foto schnell, Ausschnitt genau)"), "token": bool(TOKEN), "zugang": self._darf(q), "app": web.app_info(WEB).get("vorhanden", False), "drucker": len(BAMBU.drucker), "ha_app": HA_APP})
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
        if teile == ["preise", "abrufen"] and methode == "POST":
            im_hintergrund(preise_abrufen)
            return self._json(200, {"ok": True, "laeuft": True})
        if teile[0] == "waage" and len(teile) == 2:
            return self._json(200, waage_weiter(teile[1], methode, self._json_rumpf() if methode == "POST" else None))
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
        if teile == ["drucker"] and methode == "GET":
            return self._json(200, {"drucker": BAMBU.liste(), "mqtt": drucker_mod.mqtt is not None})
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
            return self._json(200, umzug(str(b["quelle"]), str(b.get("token") or "")))
        if teile == ["app"] and methode == "GET":
            return self._json(200, dict(web.app_info(WEB), auto=AUTO))
        if teile == ["app", "aktualisieren"] and methode == "POST":
            try:
                return self._json(200, web.aktualisieren(WEB))
            except RuntimeError as ex:
                raise Fehler(502, str(ex))
        raise Fehler(404, "Unbekannter Pfad")

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
                    ev = q.get(timeout=25)
                    self.wfile.write(("data: " + json.dumps(ev, ensure_ascii=False) + "\n\n").encode("utf-8"))
                except queue.Empty:
                    self.wfile.write(b": ping\n\n")
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            with _hoerer_lock:
                _hoerer.discard(q)

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
    print(f"SchichtLohn-Server {VERSION} · Port {PORT} · Datenbank {DB_PFAD} · Schlüssel {'an' if TOKEN else 'aus'}", flush=True)
    if OCR_AN:
        threading.Thread(target=ocr, daemon=True).start()  # Modell im Hintergrund laden
    # Als Hauptprozess im Container reagiert Python nicht von selbst auf „Stopp“ (SIGTERM) – sauber beenden
    import signal
    signal.signal(signal.SIGTERM, lambda *_: os._exit(0))
    BAMBU.neu_starten()
    if os.environ.get("AUTO_AKTUALISIEREN", "1") != "0":
        threading.Thread(target=auto_aktualisieren, daemon=True).start()
    threading.Thread(target=preise_auto, daemon=True).start()
    Server(("0.0.0.0", PORT), Handler).serve_forever()
