"""Schichtfotos: bei jedem Schichtwechsel ein Bild aus der Druckerkamera – ohne dass der Drucker anhält.

Anders als der Zeitraffer im Drucker parkt hier der Druckkopf nicht: SchichtLohn sieht im Druckerstatus,
dass eine neue Schicht anfängt (layer_num), und nimmt einfach das aktuelle Kamerabild. Der Druck läuft
dabei ganz normal weiter – der Kopf ist auf den Bildern deshalb mal hier, mal da.

Ablage: <basis>/<drucker-präfix>/<JJJJ-MM-TT_HH-MM>_<aufgabe>/schicht_0001.jpg …
Nach dem Druck macht ffmpeg daraus zeitraffer.mp4. Je Drucker bleiben die letzten AUFHEBEN Drucke.
"""
import glob
import json
import os
import re
import shutil
import subprocess
import threading
import time

LAUFEND = ("RUNNING", "PREPARE", "SLICING", "PAUSE")
AUFHEBEN = 30          # Drucke je Drucker, ältere werden gelöscht
FPS = 24               # Bilder pro Sekunde im Zeitraffer
MAX_ALTER = 3.0        # Kamerabild höchstens so alt (s), sonst auf ein neues warten


def _sauber(t, n=60):
    t = re.sub(r"\.(gcode\.)?3mf$", "", str(t or ""), flags=re.I)
    t = re.sub(r"[^\w\-. ]+", "", t, flags=re.U).strip().replace(" ", "_")
    return (t or "Druck")[:n]


class Schichtfotos:
    def __init__(self, basis, kamera_von, praefix_von, log=print):
        """kamera_von(dr) → Kamera-Objekt (kamera.py) oder None; praefix_von(dr) → „h2c_31b8…“."""
        self.basis, self.kamera_von, self.praefix_von, self.log = basis, kamera_von, praefix_von, log
        self.lock = threading.Lock()
        self.lauf = {}          # serial → {"ordner", "schicht", "bilder", "beschaeftigt"}

    # ---- vom Druckerstatus aufgerufen (oft, muss schnell sein)
    def pruefen(self, dr, an=True):
        p = getattr(dr, "p", None) or {}
        st = str(p.get("gcode_state") or "")
        serial = dr.serial
        with self.lock:
            l = self.lauf.get(serial)
            if not an or st not in LAUFEND:
                if l:
                    self.lauf.pop(serial, None)
                    if st and st not in LAUFEND:  # Druck zu Ende → Zeitraffer bauen
                        threading.Thread(target=self._abschluss, args=(l, st), daemon=True).start()
                return
            try:
                schicht = int(p.get("layer_num") or 0)
            except (TypeError, ValueError):
                schicht = 0
            name = str(p.get("subtask_name") or "")
            if l and l.get("name") != name and name:
                self.lauf.pop(serial, None)
                threading.Thread(target=self._abschluss, args=(l, "FINISH"), daemon=True).start()
                l = None
            if not l:
                if schicht <= 0:
                    return  # Aufheizen, Kalibrieren – noch keine Schicht
                ordner = os.path.join(self.basis, self.praefix_von(dr),
                                      time.strftime("%Y-%m-%d_%H-%M") + "_" + _sauber(name))
                l = self.lauf[serial] = {"ordner": ordner, "name": name, "schicht": 0, "bilder": 0,
                                         "beschaeftigt": False, "start": time.time(),
                                         "gesamt": int(p.get("total_layer_num") or 0)}
                self.log(f"Schichtfotos: {name or 'Druck'} → {ordner}")
            k = self.kamera_von(dr)
            if k is not None:
                k.anfrage = time.time()  # Kamera während des Drucks wach halten → Bild sofort da
            if st != "RUNNING" or schicht <= l["schicht"] or l["beschaeftigt"] or k is None:
                return
            l["schicht"], l["beschaeftigt"] = schicht, True
        threading.Thread(target=self._foto, args=(l, k, schicht), daemon=True).start()

    def _foto(self, l, k, schicht):
        try:
            bild = k.holen(warten=12.0, max_alter=MAX_ALTER)
            if not bild:
                return
            os.makedirs(l["ordner"], exist_ok=True)
            pfad = os.path.join(l["ordner"], "schicht_%04d.jpg" % schicht)
            with open(pfad + ".tmp", "wb") as f:
                f.write(bild)
            os.replace(pfad + ".tmp", pfad)
            l["bilder"] += 1
        except Exception as e:
            self.log(f"Schichtfotos: Bild für Schicht {schicht} fehlgeschlagen: {e}")
        finally:
            l["beschaeftigt"] = False

    # ---- nach dem Druck
    def _abschluss(self, l, st):
        time.sleep(3)  # letztes Bild fertig schreiben lassen
        ordner = l["ordner"]
        bilder = sorted(glob.glob(os.path.join(ordner, "schicht_*.jpg")))
        if not bilder:
            return
        info = {"name": l.get("name") or "", "start": int(l.get("start") or 0), "ende": int(time.time()),
                "status": "fertig" if st == "FINISH" else "abgebrochen", "bilder": len(bilder), "schichten": l.get("gesamt") or 0}
        try:
            with open(os.path.join(ordner, "info.json"), "w", encoding="utf-8") as f:
                json.dump(info, f, ensure_ascii=False)
        except OSError:
            pass
        if len(bilder) >= 2:
            self.zeitraffer(ordner)
        self.aufraeumen(os.path.dirname(ordner))

    def zeitraffer(self, ordner):
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            return None
        ziel = os.path.join(ordner, "zeitraffer.mp4")
        try:
            subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-framerate", str(FPS),
                            "-pattern_type", "glob", "-i", os.path.join(ordner, "schicht_*.jpg"),
                            "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2", "-c:v", "libx264", "-preset", "veryfast",
                            "-crf", "23", "-pix_fmt", "yuv420p", "-movflags", "+faststart", ziel + ".tmp.mp4"],
                           check=True, timeout=900, stdin=subprocess.DEVNULL, capture_output=True)
            os.replace(ziel + ".tmp.mp4", ziel)
            self.log(f"Schichtfotos: Zeitraffer fertig ({ziel})")
            return ziel
        except Exception as e:
            fehler = getattr(e, "stderr", b"") or b""
            self.log(f"Schichtfotos: Zeitraffer fehlgeschlagen: {e} {fehler[-300:].decode('utf-8', 'replace')}")
            return None

    def aufraeumen(self, drucker_ordner):
        try:
            drucke = sorted(d for d in os.listdir(drucker_ordner) if os.path.isdir(os.path.join(drucker_ordner, d)))
        except OSError:
            return
        laufend = {os.path.basename(l["ordner"]) for l in self.lauf.values()}
        for d in drucke[:-AUFHEBEN]:
            if d not in laufend:
                shutil.rmtree(os.path.join(drucker_ordner, d), ignore_errors=True)

    # ---- für die App
    def liste(self, pre=None):
        """Alle gespeicherten Drucke mit Schichtfotos, neueste zuerst."""
        aus = []
        laufend = {l["ordner"]: l for l in self.lauf.values()}
        for dp in sorted(glob.glob(os.path.join(self.basis, "*"))):
            p = os.path.basename(dp)
            if pre and p != pre:
                continue
            for d in glob.glob(os.path.join(dp, "*")):
                if not os.path.isdir(d):
                    continue
                n = len(glob.glob(os.path.join(d, "schicht_*.jpg")))
                info = {}
                try:
                    with open(os.path.join(d, "info.json"), encoding="utf-8") as f:
                        info = json.load(f)
                except (OSError, ValueError):
                    pass
                l = laufend.get(d)
                aus.append({"pre": p, "id": os.path.basename(d), "name": info.get("name") or (l or {}).get("name") or "",
                            "bilder": n, "schichten": info.get("schichten") or (l or {}).get("gesamt") or 0,
                            "status": "läuft" if l else info.get("status", ""), "start": info.get("start") or (l or {}).get("start"),
                            "zeitraffer": os.path.exists(os.path.join(d, "zeitraffer.mp4"))})
        aus.sort(key=lambda x: x["id"], reverse=True)
        return aus

    def ordner(self, pre, druck):
        pre, druck = re.sub(r"[^a-z0-9_]", "", str(pre).lower()), os.path.basename(str(druck))
        d = os.path.join(self.basis, pre, druck)
        return d if druck and not druck.startswith(".") and os.path.isdir(d) else None

    def bilder(self, pre, druck):
        d = self.ordner(pre, druck)
        return [os.path.basename(b) for b in sorted(glob.glob(os.path.join(d, "schicht_*.jpg")))] if d else []

    def datei(self, pre, druck, name):
        d = self.ordner(pre, druck)
        if not d or not re.fullmatch(r"schicht_\d{4,}\.jpg|zeitraffer\.mp4", str(name)):
            return None
        pfad = os.path.join(d, name)
        return pfad if os.path.isfile(pfad) else None

    def loeschen(self, pre, druck):
        d = self.ordner(pre, druck)
        if d and d not in {l["ordner"] for l in self.lauf.values()}:
            shutil.rmtree(d, ignore_errors=True)
            return True
        return False
