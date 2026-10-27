#!/usr/bin/env python3
"""Etikett-Leser für das SchichtLohn-Lager.

Liest von einem Spulenfoto den Etikett-Text (RapidOCR = PaddleOCR-Modelle, läuft lokal
ohne Internet) und Barcodes (zxing-cpp). Die Zuordnung zur Filament-Datenbank macht die App.

  GET  /        Status
  POST /lesen   Rumpf = Bilddatei (JPEG/PNG/HEIC-frei). Antwort:
                {"text": [{"t": "...", "p": 0.97, "box": [x, y, b, h]}], "codes": ["..."], "ms": 812, "w": 1600, "h": 1200}
"""
import io
import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import numpy as np
from PIL import Image, ImageOps

try:
    import zxingcpp
except Exception:  # Barcodes sind optional
    zxingcpp = None

from rapidocr_onnxruntime import RapidOCR

PORT = int(os.environ.get("PORT", "8093"))
MAX_BYTES = 15 * 1024 * 1024
MAX_SEITE = int(os.environ.get("MAX_SEITE", "1600"))
VERSION = "1.0.0"

OCR = RapidOCR()
OCR_LOCK = threading.Lock()  # ein Bild nach dem anderen, schont den Speicher


def bild_laden(daten):
    img = Image.open(io.BytesIO(daten))
    img = ImageOps.exif_transpose(img).convert("RGB")
    if max(img.size) > MAX_SEITE:
        img.thumbnail((MAX_SEITE, MAX_SEITE))
    return img


def barcodes(img):
    if zxingcpp is None:
        return []
    out = []
    for kandidat in (img, ImageOps.autocontrast(img.convert("L"))):
        try:
            for r in zxingcpp.read_barcodes(kandidat):
                t = (r.text or "").strip()
                if t and t not in out:
                    out.append(t)
        except Exception:
            pass
        if out:
            break
    return out


def text(img):
    with OCR_LOCK:
        res, _ = OCR(np.asarray(img)[:, :, ::-1])  # RapidOCR erwartet BGR
    out = []
    for box, t, p in res or []:
        try:
            p = float(p)
        except (TypeError, ValueError):
            p = 0.0
        if p < 0.4 or not str(t).strip():
            continue
        xs = [pt[0] for pt in box]
        ys = [pt[1] for pt in box]
        out.append({"t": str(t).strip(), "p": round(p, 3),
                    "box": [int(min(xs)), int(min(ys)), int(max(xs) - min(xs)), int(max(ys) - min(ys))]})
    return out


class Handler(BaseHTTPRequestHandler):
    server_version = "SchichtLohn-Etikett/" + VERSION

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Private-Network", "true")
        self.send_header("Access-Control-Max-Age", "86400")

    def _json(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self._cors()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self):
        if self.path.split("?")[0] in ("/", "/status"):
            return self._json(200, {"ok": True, "dienst": "etikett-leser", "version": VERSION, "barcodes": zxingcpp is not None})
        self._json(404, {"fehler": "Unbekannter Pfad"})

    def do_POST(self):
        if self.path.split("?")[0] != "/lesen":
            return self._json(404, {"fehler": "Unbekannter Pfad"})
        n = int(self.headers.get("Content-Length") or 0)
        if n <= 0 or n > MAX_BYTES:
            return self._json(413, {"fehler": "Bild fehlt oder ist zu groß (max. 15 MB)"})
        daten = self.rfile.read(n)
        t0 = time.time()
        try:
            img = bild_laden(daten)
        except Exception:
            return self._json(400, {"fehler": "Das Bild ließ sich nicht öffnen (JPEG oder PNG senden)"})
        try:
            codes = barcodes(img)
            zeilen = text(img)
        except Exception as e:
            return self._json(500, {"fehler": "Erkennung fehlgeschlagen: " + str(e)})
        self._json(200, {"text": zeilen, "codes": codes, "ms": int((time.time() - t0) * 1000),
                         "w": img.size[0], "h": img.size[1]})

    def log_message(self, fmt, *args):
        print("%s %s" % (self.address_string(), fmt % args), flush=True)


if __name__ == "__main__":
    print(f"Etikett-Leser {VERSION} hört auf Port {PORT}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
