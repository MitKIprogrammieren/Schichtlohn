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

Mit der Umgebungsvariable TOKEN verlangt der Server bei /api/* den Schlüssel
(Kopfzeile X-Token oder ?token=…). Ohne TOKEN ist alles im Heimnetz offen.
"""
import io
import json
import os
import queue
import sqlite3
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

VERSION = "2.1.0"
PORT = int(os.environ.get("PORT", "8093"))
DB_PFAD = os.environ.get("DB", "/daten/schichtlohn.db")
TOKEN = os.environ.get("TOKEN", "").strip()
MAX_BILD = 15 * 1024 * 1024
MAX_JSON = 32 * 1024 * 1024
MAX_SEITE = int(os.environ.get("MAX_SEITE", "1600"))
OCR_AN = os.environ.get("OCR", "1") != "0"
MERKMAL_MODELL = os.environ.get("MERKMAL_MODELL", "/app/modelle/mnv2_merkmale.onnx")

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


def ocr():
    global _ocr
    if _ocr is None:
        from rapidocr_onnxruntime import RapidOCR
        _ocr = RapidOCR()
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
    m = (sat > 0.35) & (mx > 0.18)
    if m.sum() >= h * wd * 0.004:
        X, W = a[m], cw[m] * sat[m] ** 2
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
        def lesen(bild):
            with _ocr_lock:
                res, _ = ocr()(np.asarray(bild)[:, :, ::-1])
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


class Handler(BaseHTTPRequestHandler):
    server_version = "SchichtLohn-Server/" + VERSION
    protocol_version = "HTTP/1.1"

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Token")
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

    def _rumpf(self, grenze):
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
        return t == TOKEN

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _route(self, methode):
        pfad, q = self._pfad()
        if pfad in ("/", "/status") and methode == "GET":
            return self._json(200, {"ok": True, "dienst": "schichtlohn-server", "version": VERSION, "datenbank": True,
                                    "etikett": OCR_AN, "lernen": os.path.exists(MERKMAL_MODELL), "token": bool(TOKEN), "zugang": self._darf(q)})
        if pfad == "/lesen" and methode == "POST":
            t0 = time.time()
            daten = self._rumpf(MAX_BILD)
            try:
                r = bild_lesen(daten, ausschnitt=(q.get("ausschnitt") or ["0"])[0] == "1")
            except Exception as e:
                raise Fehler(400, "Das Bild ließ sich nicht auswerten: " + str(e))
            r["ms"] = int((time.time() - t0) * 1000)
            return self._json(200, r)
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
        if teile == ["sorten"] and methode == "GET":
            return self._json(200, {"sorten": sorten()})
        if teile == ["sicherung"] and methode == "GET":
            return self._json(200, sicherung())
        if teile == ["ereignisse"] and methode == "GET":
            return self._sse()
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


class Server(ThreadingHTTPServer):
    daemon_threads = True


if __name__ == "__main__":
    db()
    print(f"SchichtLohn-Server {VERSION} · Port {PORT} · Datenbank {DB_PFAD} · Schlüssel {'an' if TOKEN else 'aus'}", flush=True)
    if OCR_AN:
        threading.Thread(target=ocr, daemon=True).start()  # Modell im Hintergrund laden
    Server(("0.0.0.0", PORT), Handler).serve_forever()
