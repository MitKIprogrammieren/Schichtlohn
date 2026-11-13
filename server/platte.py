"""Leere-Platte-Prüfung: Kamerabild gegen Referenzbilder der leeren Druckplatte vergleichen.

Je Drucker liegen bis zu 6 Referenzbilder (verschiedenes Licht, verschiedene Platten). Verglichen wird mit jedem,
das beste Ergebnis zählt. Vorgehen: Graustufen, verkleinern, weichzeichnen, Helligkeit angleichen, Unterschied
bilden, Lichtreflexe der Referenz ausblenden, kleine Störungen wegfiltern, zusammenhängende Flächen zählen.
"""
import os
import re
import threading
import time

import cv2
import numpy as np

MAX_REFS = 6
BREITE = 320          # Arbeitsbreite in Pixeln
PIX_DIFF = 30         # ab dieser Helligkeitsdifferenz (0–255) gilt ein Pixel als verändert
MIN_TEIL = 0.001      # zusammenhängende Fläche ab 0,1 % des Bildes gilt als Teil
ZU_DUNKEL = 22        # mittlere Helligkeit darunter: Licht aus, keine verlässliche Aussage
NAME_RE = re.compile(r"^ref_\d+\.jpg$")


def _grau(jpg):
    img = cv2.imdecode(np.frombuffer(jpg, np.uint8), cv2.IMREAD_GRAYSCALE)
    if img is None:
        raise ValueError("Bild nicht lesbar")
    h, w = img.shape
    img = cv2.resize(img, (BREITE, max(1, round(h * BREITE / w))), interpolation=cv2.INTER_AREA)
    return cv2.GaussianBlur(img, (5, 5), 0)


def vergleichen(akt, ref):
    """→ (teile, anteil in %) – wie stark sich das aktuelle Bild von der leeren Platte unterscheidet."""
    if akt.shape != ref.shape:
        akt = cv2.resize(akt, (ref.shape[1], ref.shape[0]), interpolation=cv2.INTER_AREA)
    m_akt, m_ref = float(akt.mean()), float(ref.mean())
    a = akt.astype(np.float32) * (m_ref / m_akt if m_akt > 1 else 1.0)
    diff = np.abs(a - ref.astype(np.float32))
    maske = (diff > PIX_DIFF).astype(np.uint8)
    reflex = ref.astype(np.float32) > max(170.0, 1.9 * float(np.median(ref)))
    maske[reflex] = 0
    maske = cv2.morphologyEx(maske, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    n, _, stats, _ = cv2.connectedComponentsWithStats(maske, connectivity=8)
    gesamt = maske.size
    teile = sum(1 for i in range(1, n) if stats[i, cv2.CC_STAT_AREA] >= MIN_TEIL * gesamt)
    return teile, round(float(maske.sum()) * 100 / gesamt, 2)


class Platte:
    def __init__(self, basis):
        self.basis = basis
        self.lock = threading.Lock()
        self.ergebnis = {}      # pre → letztes Prüfergebnis
        self.laeuft = set()

    def _ordner(self, pre):
        return os.path.join(self.basis, re.sub(r"[^a-z0-9_]", "", pre.lower()))

    def refs(self, pre):
        d = self._ordner(pre)
        if not os.path.isdir(d):
            return []
        namen = sorted((n for n in os.listdir(d) if NAME_RE.match(n)), key=lambda n: int(n[4:-4]))
        return [{"name": n, "zeit": int(os.path.getmtime(os.path.join(d, n)))} for n in namen]

    def ref_bild(self, pre, name):
        if not NAME_RE.match(name or ""):
            return None
        p = os.path.join(self._ordner(pre), name)
        if not os.path.isfile(p):
            return None
        with open(p, "rb") as f:
            return f.read()

    def merken(self, pre, jpg):
        if float(_grau(jpg).mean()) < ZU_DUNKEL:
            raise ValueError("Das Kamerabild ist zu dunkel – bitte erst das Licht einschalten")
        with self.lock:
            d = self._ordner(pre)
            os.makedirs(d, exist_ok=True)
            alt = self.refs(pre)
            for r in alt[:max(0, len(alt) - MAX_REFS + 1)]:
                os.remove(os.path.join(d, r["name"]))
            nr = max((int(r["name"][4:-4]) for r in alt), default=0) + 1
            with open(os.path.join(d, f"ref_{nr}.jpg"), "wb") as f:
                f.write(jpg)
            self.ergebnis.pop(pre, None)
        return self.refs(pre)

    def loeschen(self, pre, name):
        if not NAME_RE.match(name or ""):
            raise ValueError("Unbekanntes Bild")
        with self.lock:
            p = os.path.join(self._ordner(pre), name)
            if os.path.isfile(p):
                os.remove(p)
            self.ergebnis.pop(pre, None)
        return self.refs(pre)

    def pruefen(self, pre, jpg):
        """→ {frei, teile, anteil, zeit} oder {dunkel: True, …}; None, wenn es kein Referenzbild gibt."""
        refs = self.refs(pre)
        if not refs:
            return None
        akt = _grau(jpg)
        if float(akt.mean()) < ZU_DUNKEL:
            erg = {"dunkel": True, "zeit": int(time.time())}
        else:
            bestes = None
            for r in refs:
                try:
                    ref = _grau(self.ref_bild(pre, r["name"]))
                except Exception:
                    continue
                teile, anteil = vergleichen(akt, ref)
                if bestes is None or (teile, anteil) < bestes:
                    bestes = (teile, anteil)
            if bestes is None:
                return None
            erg = {"frei": bestes[0] == 0, "teile": bestes[0], "anteil": bestes[1], "zeit": int(time.time())}
        self.ergebnis[pre] = erg
        return erg

    def im_hintergrund(self, pre, foto_fn, log=print):
        """Prüfung in eigenem Faden starten (höchstens eine je Drucker gleichzeitig)."""
        with self.lock:
            if pre in self.laeuft:
                return
            self.laeuft.add(pre)

        def lauf():
            try:
                jpg = foto_fn(pre)
                if jpg:
                    self.pruefen(pre, jpg)
            except Exception as e:
                log(f"Plattenprüfung {pre}: {e}")
            finally:
                with self.lock:
                    self.laeuft.discard(pre)
        threading.Thread(target=lauf, daemon=True).start()
