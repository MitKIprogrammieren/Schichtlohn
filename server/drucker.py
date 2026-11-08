"""Bambu-Lab-Drucker direkt anbinden (MQTT) – wie Bambuddy bzw. die Bambu-Integration in Home Assistant.

Je Drucker eine Verbindung:
  lokal  – Heimnetz: IP, Seriennummer, Zugangscode (Benutzer „bblp“, Port 8883, TLS)
  cloud  – Bambu-Cloud: Anmeldung (Token) aus SchichtLohn, us.mqtt.bambulab.com

Aus den Meldungen entstehen Zustände im Format von Home Assistant (sensor.<modell>_<seriennr>_druckstatus,
…_ams_1_slot_2 usw.), damit das Lager und die Waage sie unverändert anzeigen.

Bei Druckende (FINISH) bzw. Abbruch (FAILED) werden die Gramm je Filament ermittelt:
  1. aus der Druckdatei (.3mf, Metadata/slice_info.config) – lokal per FTPS vom Drucker
  2. aus der Cloud-Druckaufgabe (amsDetailMapping)
  3. aus der Abnahme der AMS-Restanzeige (nur Bambu-Spulen mit Chip)
und dem Lager übergeben (Rückruf abbuchen).
"""
import ftplib
import io
import os
import json
import re
import socket
import ssl
import threading
import time
import urllib.parse
import urllib.request
import uuid
import xml.etree.ElementTree as ET
import zipfile

try:
    import paho.mqtt.client as mqtt
except ImportError:  # Tests ohne paho
    mqtt = None

CLOUD_API = {"global": "https://api.bambulab.com", "china": "https://api.bambulab.cn"}
CLOUD_MQTT = {"global": "us.mqtt.bambulab.com", "china": "cn.mqtt.bambulab.com"}
KOPF = {
    "User-Agent": "bambu_network_agent/01.09.05.01",
    "X-BBL-Client-Name": "OrcaSlicer", "X-BBL-Client-Type": "slicer", "X-BBL-Client-Version": "01.09.05.51",
    "X-BBL-Language": "de-DE", "X-BBL-OS-Type": "linux", "X-BBL-OS-Version": "6.2.0",
    "X-BBL-Agent-Version": "01.09.05.01", "X-BBL-Executable-info": "{}", "X-BBL-Agent-OS-Type": "linux",
    "Accept": "application/json",
}
# Seriennummer → Modell (wie die Entitätsnamen in Home Assistant)
MODELLE = [("00M", "x1c"), ("00W", "x1"), ("03W", "x1e"), ("01S", "p1p"), ("01P", "p1s"), ("22E", "p2s"),
           ("030", "a1mini"), ("039", "a1"), ("094", "h2d"), ("239", "h2d"), ("093", "h2s"), ("31B", "h2c")]
MODELL_NAMEN = {"x1c": "X1C", "x1": "X1", "x1e": "X1E", "p1p": "P1P", "p1s": "P1S", "p2s": "P2S", "a1mini": "A1 mini",
                "a1": "A1", "h2d": "H2D", "h2s": "H2S", "h2c": "H2C"}
LAUFEND = ("RUNNING", "PAUSE", "PREPARE", "SLICING")


def modell_aus_serie(serie, produkt=""):
    p = re.sub(r"[^a-z0-9]", "", str(produkt or "").lower())
    for k, n in MODELL_NAMEN.items():
        if p and p == re.sub(r"[^a-z0-9]", "", n.lower()):
            return k
    s = str(serie or "").upper()
    for pre, m in MODELLE:
        if s.startswith(pre):
            return m
    return "bambu"


def praefix(d):
    m = re.sub(r"[^a-z0-9]", "", str(d.get("modell") or modell_aus_serie(d.get("serial"))).lower()) or "bambu"
    return f"{m}_{str(d.get('serial') or '').lower()}"


def tief_mischen(a, b):
    for k, v in b.items():
        if isinstance(v, dict) and isinstance(a.get(k), dict):
            tief_mischen(a[k], v)
        else:
            a[k] = v
    return a


def _int(x, std=None):
    try:
        return int(float(x))
    except (TypeError, ValueError):
        return std


def _farbe(c):
    c = str(c or "").strip().lstrip("#")
    return ("#" + c[:6].lower()) if re.fullmatch(r"[0-9a-fA-F]{6}([0-9a-fA-F]{2})?", c) else ""


def ort_name(ams_id, fach):
    """Wie im HA-Skript: „AMS 1 Fach 2“, „AMS HT 1“, „Externe Spule“."""
    if ams_id is None:
        return "Externe Spule" if not fach else f"Externe Spule {fach + 1}"
    if ams_id >= 128:
        return f"AMS HT {ams_id - 127}"
    return f"AMS {ams_id + 1} Fach {fach + 1}"


# ---------------------------------------------------------------- Fächer aus der Meldung

AMS_TYP = {"ams": 1, "ams_lite": 2, "n3f": 3, "n3s": 4, "f1": 2}


def ams_module_map(dr):
    """Aus der get_version-Modul-Liste: {ams_id (wie in der Meldung): {"sn": Seriennummer, "typ": AMS-Typ}}.
    Modulname ist z. B. "n3f/0" oder "n3s/128" – die Zahl ist genau die ams_id aus push_status."""
    out = {}
    for m in getattr(dr, "module", []) or []:
        if not isinstance(m, dict):
            continue
        name = str(m.get("name") or "")
        if "/" not in name:
            continue
        pre, _, num = name.partition("/")
        if not num.lstrip("-").isdigit():
            continue
        typ = AMS_TYP.get(pre.lower())
        if typ is None:
            continue
        out[int(num)] = {"sn": str(m.get("sn") or ""), "typ": typ}
    return out


def faecher(p):
    """Alle belegten und leeren Fächer: [{ams, fach, global, ort, fid, farbe, typ, name, rest, gewicht, tag, leer}]"""
    out = []
    ams = (p.get("ams") or {}).get("ams") or []
    for a in ams:
        aid = _int(a.get("id"), 0)
        for t in a.get("tray") or []:
            tid = _int(t.get("id"), 0)
            leer = not t.get("tray_type")
            out.append({"ams": aid, "fach": tid, "global": aid * 4 + tid if aid < 128 else aid, "ort": ort_name(aid, tid),
                        "fid": str(t.get("tray_info_idx") or ""), "farbe": _farbe(t.get("tray_color")),
                        "farbe_roh": str(t.get("tray_color") or ""), "typ": str(t.get("tray_type") or ""),
                        "name": str(t.get("tray_sub_brands") or t.get("tray_type") or ""), "rest": _int(t.get("remain"), -1),
                        "gewicht": _int(t.get("tray_weight"), 0), "tag": str(t.get("tag_uid") or ""), "leer": leer,
                        "feuchte": a.get("humidity"), "feuchte_roh": a.get("humidity_raw"), "trocknen": _int(a.get("dry_time"), 0)})
    externe = []
    if isinstance(p.get("vt_tray"), dict):
        externe.append(p["vt_tray"])
    for v in p.get("vir_slot") or []:
        if isinstance(v, dict) and v not in externe:
            externe.append(v)
    for i, t in enumerate(externe[:2]):
        leer = not t.get("tray_type")
        out.append({"ams": None, "fach": i, "global": 254 if i == 0 else 255, "ort": ort_name(None, i),
                    "fid": str(t.get("tray_info_idx") or ""), "farbe": _farbe(t.get("tray_color")),
                    "farbe_roh": str(t.get("tray_color") or ""), "typ": str(t.get("tray_type") or ""),
                    "name": str(t.get("tray_sub_brands") or t.get("tray_type") or ""), "rest": _int(t.get("remain"), -1),
                    "gewicht": _int(t.get("tray_weight"), 0), "tag": str(t.get("tag_uid") or ""), "leer": leer})
    return out


def zustaende(d, p, online):
    """Meldung → HA-ähnliche Zustände {entity_id: (state, attributes)}"""
    pre = praefix(d)
    name = d.get("name") or MODELL_NAMEN.get(d.get("modell") or modell_aus_serie(d.get("serial")), "Drucker")
    st = str(p.get("gcode_state") or "unknown").lower() if online else "offline"
    z = {
        f"sensor.{pre}_druckstatus": (st, {"friendly_name": f"{name} Druckstatus", "drucker_name": name, "quelle": "schichtlohn"}),
        f"sensor.{pre}_druckfortschritt": (str(_int(p.get("mc_percent"), 0)), {"unit_of_measurement": "%", "friendly_name": f"{name} Druckfortschritt"}),
        f"sensor.{pre}_verbleibende_zeit": (str(_int(p.get("mc_remaining_time"), 0)), {"unit_of_measurement": "min", "friendly_name": f"{name} Restzeit"}),
        f"sensor.{pre}_aktuelle_aufgabe": (str(p.get("subtask_name") or ""), {"friendly_name": f"{name} Aufgabe"}),
    }
    tray_now = _int((p.get("ams") or {}).get("tray_now"), 255)
    gesehen = set()
    for f in faecher(p):
        if f["ams"] is None:
            eid = f"sensor.{pre}_externalspool{'' if f['fach'] == 0 else f['fach'] + 1}_externe_spule"
        else:
            idx = f["ams"] + 1 if f["ams"] < 128 else f["ams"]
            eid = f"sensor.{pre}_ams_{idx}_slot_{f['fach'] + 1}"
            if idx not in gesehen:
                gesehen.add(idx)
                if f.get("feuchte_roh") not in (None, ""):
                    z[f"sensor.{pre}_ams_{idx}_luftfeuchtigkeit"] = (str(f["feuchte_roh"]), {"unit_of_measurement": "%"})
                if f.get("feuchte") not in (None, ""):
                    z[f"sensor.{pre}_ams_{idx}_index_der_luftfeuchtigkeit"] = (str(f["feuchte"]), {})
                z[f"binary_sensor.{pre}_ams_{idx}_trocknen"] = ("on" if f.get("trocknen") else "off", {})
        farbe = ("#" + f["farbe_roh"].upper()) if f["farbe"] else ""
        z[eid] = (f["name"] or ("Leer" if f["leer"] else "?"), {
            "name": f["name"], "color": farbe, "type": f["typ"], "remain": f["rest"], "filament_id": f["fid"],
            "empty": f["leer"], "active": f["global"] == tray_now, "tag_uid": f["tag"], "tray_weight": f["gewicht"],
            "friendly_name": f"{name} {f['ort']}"})
    return z


# ---------------------------------------------------------------- Gramm je Filament

def slice_info(daten, platte=None):
    """3MF-Inhalt → [{id, fid, typ, farbe, gramm}] der gewählten Platte."""
    with zipfile.ZipFile(io.BytesIO(daten)) as z:
        xml = z.read("Metadata/slice_info.config")
    root = ET.fromstring(xml)
    wahl = _platte_wahl(root, platte)
    if wahl is None:
        return []
    out = []
    for f in wahl.findall("filament"):
        g = float(f.get("used_g") or 0)
        if g > 0:
            out.append({"id": _int(f.get("id"), 0), "fid": f.get("tray_info_idx") or "", "typ": f.get("type") or "",
                        "farbe": _farbe(f.get("color")), "gramm": g})
    return out


def datei_kopf(daten, platte=None):
    """3MF-Inhalt → Kurzinfo der gewählten Platte: {platte, minuten, gramm, filamente[{typ, farbe, gramm}], bild (PNG-Bytes oder None)}"""
    with zipfile.ZipFile(io.BytesIO(daten)) as z:
        root = ET.fromstring(z.read("Metadata/slice_info.config"))
        wahl = _platte_wahl(root, platte)
        meta = {m.get("key"): m.get("value") for m in (wahl.findall("metadata") if wahl is not None else [])}
        idx = _int(meta.get("index"), platte or 1) or 1
        namen = set(z.namelist())
        bild = None
        for n in (f"Metadata/plate_{idx}.png", f"Metadata/plate_{idx}_small.png", "Metadata/plate_1.png", "Metadata/thumbnail.png"):
            if n in namen:
                bild = z.read(n)
                break
    fil = []
    for f in (wahl.findall("filament") if wahl is not None else []):
        g = float(f.get("used_g") or 0)
        if g > 0:
            fil.append({"typ": f.get("type") or "", "farbe": _farbe(f.get("color")), "fid": f.get("tray_info_idx") or "", "gramm": round(g, 2)})
    gramm = sum(f["gramm"] for f in fil) or float(meta.get("weight") or 0)
    return {"platte": idx, "minuten": round(float(meta.get("prediction") or 0) / 60), "gramm": round(gramm, 2), "filamente": fil, "bild": bild}


_LIST_RE = re.compile(r"^[-d][rwx-]{9}\S*\s+\d+\s+\S+\s+\S+\s+(\d+)\s+(\w{3})\s+(\d{1,2})\s+(\d{1,2}:\d{2}|\d{4})\s+(.+)$")
_MONATE = {m: i + 1 for i, m in enumerate(["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"])}
SPEICHER_ORDNER = ("/", "/cache", "/model", "/sdcard")
SPEICHER_OHNE = {"timelapse", "logger", "corelogger", "ipcam", "recorder", "log", "logs", "image", "images", "verify_job", "system"}
SPEICHER_MAX_MB = 80


def _list_zeit(mon, tag, rest):
    """Datum aus einer LIST-Zeile (ohne Jahr = innerhalb der letzten 12 Monate)."""
    jetzt = time.localtime()
    try:
        if ":" in rest:
            h, mi = rest.split(":")
            t = time.mktime((jetzt.tm_year, _MONATE.get(mon, 1), int(tag), int(h), int(mi), 0, 0, 0, -1))
            if t > time.time() + 86400:
                t = time.mktime((jetzt.tm_year - 1, _MONATE.get(mon, 1), int(tag), int(h), int(mi), 0, 0, 0, -1))
            return t
        return time.mktime((int(rest), _MONATE.get(mon, 1), int(tag), 12, 0, 0, 0, 0, -1))
    except (ValueError, OverflowError):
        return 0


def speicher_lesen(ip, code, bekannt=None, timeout=25, max_dateien=3000, ziel=None):
    """Druckdateien (.3mf) im Speicher des Druckers auflisten und auswerten.
    bekannt: {pfad: eintrag} aus dem letzten Lauf – unveränderte Dateien (gleiche Größe) werden nicht neu geladen.
    → [{pfad, titel, groesse, zeit, platte, minuten, gramm, filamente, bild (Bytes oder None, nur bei neu geladenen)}]"""
    bekannt = bekannt or {}
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    ftp = _FTPS(context=ctx, timeout=timeout)
    ftp.connect(ip, 990)
    try:
        ftp.login("bblp", code)
        ftp.prot_p()
        dateien, gesehen, besucht = [], set(), set()
        offen = [(o, 0) for o in SPEICHER_ORDNER]
        while offen:  # alle Ordner bis zwei Ebenen tief (Bambu Studio legt Dateien je nach Firmware in Unterordner)
            ordner, tiefe = offen.pop(0)
            if ordner in besucht:
                continue
            besucht.add(ordner)
            zeilen = []
            try:
                ftp.dir(ordner, zeilen.append)
            except ftplib.all_errors:
                continue
            for z in zeilen:
                m = _LIST_RE.match(z.strip())
                if not m:
                    continue
                name = m.group(5).strip()
                if z.startswith("d"):
                    if tiefe < 2 and name not in (".", "..") and name.lower() not in SPEICHER_OHNE:
                        offen.append((ordner.rstrip("/") + "/" + name, tiefe + 1))
                    continue
                if not name.lower().endswith(".3mf") or name in gesehen:
                    continue
                gesehen.add(name)
                pfad = ordner.rstrip("/") + "/" + name
                dateien.append({"pfad": pfad, "name": name, "groesse": int(m.group(1)), "zeit": _list_zeit(m.group(2), m.group(3), m.group(4))})
        dateien.sort(key=lambda d: -d["zeit"])
        out = []
        for d in dateien[:max_dateien]:
            titel = re.sub(r"(\.gcode)?\.3mf$", "", d["name"], flags=re.I)
            alt = bekannt.get(d["pfad"])
            kopie = os.path.join(ziel, d["name"]) if ziel else None
            gesichert = bool(kopie and os.path.exists(kopie) and os.path.getsize(kopie) == d["groesse"])
            if alt and alt.get("groesse") == d["groesse"] and (gesichert or not ziel):
                out.append(dict(alt, zeit=d["zeit"] or alt.get("zeit", 0), bild=None, gesichert=gesichert))
                continue
            e = {"pfad": d["pfad"], "titel": titel, "groesse": d["groesse"], "zeit": d["zeit"], "platte": None, "minuten": 0,
                 "gramm": 0, "filamente": [], "bild": None, "fehler": ""}
            if d["groesse"] > SPEICHER_MAX_MB * 1024 * 1024:
                e["fehler"] = "Datei zu groß"
                out.append(e)
                continue
            puffer = io.BytesIO()
            try:
                ftp.retrbinary("RETR " + d["pfad"], puffer.write)
                if kopie:  # Kopie der Druckdatei auf dem Server ablegen
                    os.makedirs(ziel, exist_ok=True)
                    with open(kopie + ".neu", "wb") as f:
                        f.write(puffer.getvalue())
                    os.replace(kopie + ".neu", kopie)
                    e["gesichert"] = True
                m = re.search(r"plate_(\d+)", d["name"])
                e.update(datei_kopf(puffer.getvalue(), int(m.group(1)) if m else None))
            except ftplib.all_errors as ex:
                e["fehler"] = f"nicht lesbar: {ex}"
            except Exception as ex:  # keine gültige Druckdatei
                e["fehler"] = f"nicht auswertbar: {ex}"
            out.append(e)
        return out
    finally:
        try:
            ftp.close()
        except Exception:
            pass


def _platte_wahl(root, platte):
    platten = root.findall("plate")
    if not platten:
        return None
    if platte is not None:
        for pl in platten:
            idx = next((m.get("value") for m in pl.findall("metadata") if m.get("key") == "index"), None)
            if _int(idx) == platte:
                return pl
    return platten[0]


def objekte(daten, platte=None):
    """3MF-Inhalt → {identify_id: name} der Objekte auf der gewählten Platte (diese IDs meldet der Drucker in s_obj)."""
    with zipfile.ZipFile(io.BytesIO(daten)) as z:
        root = ET.fromstring(z.read("Metadata/slice_info.config"))
    wahl = _platte_wahl(root, platte)
    out = {}
    for o in (wahl.findall("object") if wahl is not None else []):
        i = _int(o.get("identify_id"))
        if i is not None:
            out[i] = o.get("name") or ""
    return out


_RE_LAYER = re.compile(r";\s*layer num/total_layer_count:\s*(\d+)")
_RE_START = re.compile(r";\s*(?:start printing object, unique label id:\s*(\d+)|printing object .*?\bid:\s*(\d+))")
_RE_STOP = re.compile(r";\s*stop printing object")
_RE_E = re.compile(r"\bE(-?\d*\.?\d+)")
_RE_T = re.compile(r"^T(\d+)\b")


def gcode_auswerten(daten, platte=None):
    """Filament je (Schicht, Objekt, Werkzeug) aus dem G-Code in der 3MF.
    → {"e": {(schicht, objekt|None, werkzeug): mm}, "schichten": n} oder None, wenn kein G-Code drin ist.
    So lässt sich ausrechnen, wie viel von übersprungenen Teilen nicht mehr gedruckt wurde."""
    with zipfile.ZipFile(io.BytesIO(daten)) as z:
        namen = [n for n in z.namelist() if re.fullmatch(r"Metadata/plate_\d+\.gcode", n)]
        if not namen:
            return None
        name = f"Metadata/plate_{platte}.gcode" if f"Metadata/plate_{platte}.gcode" in namen else namen[0]
        e, schicht, zaehler, nummer_da, obj, werkzeug, absolut, letztes_e = {}, 0, 0, False, None, 0, False, 0.0
        with z.open(name) as roh:
            for zeile in io.TextIOWrapper(roh, encoding="utf-8", errors="replace"):
                if zeile.startswith(";"):
                    m = _RE_LAYER.match(zeile)
                    if m:
                        schicht, nummer_da = int(m.group(1)), True
                        continue
                    if zeile.startswith("; CHANGE_LAYER"):
                        zaehler += 1
                        if not nummer_da:
                            schicht = zaehler
                        continue
                    m = _RE_START.match(zeile)
                    if m:
                        obj = int(m.group(1) or m.group(2))
                        continue
                    if _RE_STOP.match(zeile):
                        obj = None
                    continue
                c = zeile[:3]
                if c in ("G1 ", "G0 ", "G2 ", "G3 "):
                    m = _RE_E.search(zeile.split(";", 1)[0])
                    if not m:
                        continue
                    wert = float(m.group(1))
                    if absolut:
                        wert, letztes_e = wert - letztes_e, wert
                    k = (schicht, obj, werkzeug)
                    e[k] = e.get(k, 0.0) + wert
                elif zeile.startswith("T"):
                    m = _RE_T.match(zeile)
                    if m and int(m.group(1)) < 64:
                        werkzeug = int(m.group(1))
                elif zeile.startswith("M82"):
                    absolut = True
                elif zeile.startswith("M83"):
                    absolut = False
                elif zeile.startswith("G92") and absolut:
                    m = _RE_E.search(zeile)
                    if m:
                        letztes_e = float(m.group(1))
    return {"e": e, "schichten": max(schicht, zaehler)}


def gedruckter_anteil(g, uebersprungen, bis_schicht=None):
    """Anteil je Werkzeug, der wirklich gedruckt wurde.
    uebersprungen = {objekt: schicht beim Überspringen}; bis_schicht = letzte gedruckte Schicht bei Abbruch (None = fertig)."""
    gesamt, gedruckt = {}, {}
    for (s, o, w), mm in g["e"].items():
        gesamt[w] = gesamt.get(w, 0.0) + mm
        if bis_schicht is not None and s > bis_schicht:
            continue
        if o is not None and o in uebersprungen and s > uebersprungen[o]:
            continue
        gedruckt[w] = gedruckt.get(w, 0.0) + mm
    return {w: (min(1.0, max(0.0, gedruckt.get(w, 0.0) / t)) if t > 0 else 1.0) for w, t in gesamt.items()}


class _FTPS(ftplib.FTP_TLS):
    """Implizites FTPS (Port 990) mit Wiederverwendung der TLS-Sitzung – so verlangt es der Drucker."""

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self._sock = None

    @property
    def sock(self):
        return self._sock

    @sock.setter
    def sock(self, wert):
        if wert is not None and not isinstance(wert, ssl.SSLSocket):
            wert = self.context.wrap_socket(wert)
        self._sock = wert

    def ntransfercmd(self, cmd, rest=None):
        conn, size = ftplib.FTP.ntransfercmd(self, cmd, rest)
        if self._prot_p:
            conn = self.context.wrap_socket(conn, server_hostname=self.host, session=self.sock.session)
        return conn, size


def druckdatei_laden(ip, code, p, timeout=25):
    """Druckdatei (.3mf) vom Drucker holen. → (bytes, pfad) oder (None, grund)"""
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    ftp = _FTPS(context=ctx, timeout=timeout)
    try:
        ftp.connect(ip, 990)
        ftp.login("bblp", code)
        ftp.prot_p()
        kandidaten = []
        gf = str(p.get("gcode_file") or "")
        if gf.lower().endswith(".3mf"):
            kandidaten.append(gf if gf.startswith("/") else "/" + gf)
        name = str(p.get("subtask_name") or "").strip()
        if name:
            for ordner in ("/", "/cache/", "/model/", "/sdcard/"):
                for endung in (".gcode.3mf", ".3mf", ""):
                    if endung or name.lower().endswith(".3mf"):
                        kandidaten.append(ordner + name + endung)
        for k in kandidaten:
            puffer = io.BytesIO()
            try:
                ftp.retrbinary("RETR " + k, puffer.write)
            except ftplib.all_errors:
                continue
            if puffer.tell() > 0:
                return puffer.getvalue(), k
        return None, "Druckdatei nicht auf dem Drucker gefunden (in Bambu Studio „Gesendete Dateien auf externem Speicher speichern“ einschalten)"
    except ftplib.all_errors as e:
        return None, f"FTP: {e}"
    finally:
        try:
            ftp.close()
        except Exception:
            pass


def platte_aus(p):
    for k in ("gcode_file", "param"):
        m = re.search(r"plate_(\d+)\.gcode", str(p.get(k) or ""))
        if m:
            return int(m.group(1))
    return None


def datei_platten(daten):
    """3MF-Inhalt → (printer_model_id, [{platte, minuten, gramm, filamente[{id, fid, typ, farbe, gramm}]}]) aller Platten mit G-Code."""
    with zipfile.ZipFile(io.BytesIO(daten)) as z:
        root = ET.fromstring(z.read("Metadata/slice_info.config"))
        namen = set(z.namelist())
    modell, out = "", []
    for pl in root.findall("plate"):
        meta = {m.get("key"): m.get("value") for m in pl.findall("metadata")}
        idx = _int(meta.get("index"), 0)
        modell = modell or meta.get("printer_model_id") or ""
        if not idx or f"Metadata/plate_{idx}.gcode" not in namen:
            continue
        fil = [{"id": _int(f.get("id"), 0), "fid": f.get("tray_info_idx") or "", "typ": f.get("type") or "",
                "farbe": _farbe(f.get("color")), "gramm": float(f.get("used_g") or 0)} for f in pl.findall("filament")]
        out.append({"platte": idx, "minuten": round(_int(meta.get("prediction"), 0) / 60), "gramm": round(float(meta.get("weight") or 0), 2),
                    "filamente": fil, "duese": meta.get("nozzle_diameters") or ""})
    return modell, out


def modell_id(daten):
    """Nur die printer_model_id aus der 3MF (für den Abgleich Datei ↔ Drucker)."""
    try:
        with zipfile.ZipFile(io.BytesIO(daten)) as z:
            root = ET.fromstring(z.read("Metadata/slice_info.config"))
        for pl in root.findall("plate"):
            for m in pl.findall("metadata"):
                if m.get("key") == "printer_model_id" and m.get("value"):
                    return m.get("value")
    except Exception:
        pass
    return ""


def hochladen(ip, code, name, daten, timeout=60):
    """Druckdatei per FTPS ins Hauptverzeichnis des Druckers legen (dort erwartet ihn der Startbefehl). → (ok, text)"""
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    ftp = _FTPS(context=ctx, timeout=timeout)
    try:
        ftp.connect(ip, 990)
        ftp.login("bblp", code)
        ftp.prot_p()
        ftp.storbinary("STOR /" + name, io.BytesIO(daten))
        return True, "hochgeladen"
    except ftplib.all_errors as e:
        return False, f"Hochladen ging nicht: {e}"
    finally:
        try:
            ftp.close()
        except Exception:
            pass


def zuordnen(filamente, faecher_liste):
    """Filament aus der Druckdatei → Fach im AMS (gleiche Bambu-ID, gleiches Material, nächste Farbe)."""
    belegt = [f for f in faecher_liste if not f["leer"]]
    out = []
    for fi in filamente:
        bester, wert = None, -1e9
        for f in belegt:
            w = 0
            if fi["fid"] and f["fid"] == fi["fid"]:
                w += 50
            if fi["typ"] and f["typ"].upper() == fi["typ"].upper():
                w += 20
            if fi["farbe"] and f["farbe"]:
                w -= farbabstand(fi["farbe"], f["farbe"]) / 1000
            if w > wert:
                bester, wert = f, w
        out.append((fi, bester))
    return out


# ---------------------------------------------------------------- Heimnetz zusätzlich zur Cloud (nur für die Druckdatei)

def lan_pruefen(ip, code, timeout=6):
    """Kommt der Server per FTPS (Port 990) mit dem Zugangscode an den Speicher des Druckers? → (ok, text)"""
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    ftp = _FTPS(context=ctx, timeout=timeout)
    try:
        ftp.connect(ip, 990)
        ftp.login("bblp", code)
        ftp.prot_p()
        ftp.nlst("/")
        return True, f"Druckerspeicher unter {ip} erreichbar"
    except ftplib.error_perm as e:
        return False, "Zugangscode passt nicht" if "530" in str(e) else f"Drucker lehnt ab: {e}"
    except ConnectionRefusedError:
        return False, f"{ip} lässt keinen Dateizugriff zu – stimmt die IP? Manche Drucker brauchen dafür den LAN-Modus"
    except ftplib.all_errors as e:
        return False, f"{ip} nicht erreichbar ({fehlertext(e)})"
    finally:
        try:
            ftp.close()
        except Exception:
            pass


def lan_suchen(code, netze, zeit=0.5):
    """Drucker im Heimnetz finden: Port 990 in den Netzen (z. B. „192.168.1“) abklopfen, dann mit dem Zugangscode anmelden.
    → (ip oder "", text)"""
    from concurrent.futures import ThreadPoolExecutor

    def offen(ip):
        try:
            with socket.create_connection((ip, 990), timeout=zeit):
                return ip
        except OSError:
            return None
    kandidaten = [f"{n}.{i}" for n in netze for i in range(1, 255)]
    with ThreadPoolExecutor(max_workers=96) as ex:
        treffer = [ip for ip in ex.map(offen, kandidaten) if ip]
    if not treffer:
        return "", f"Kein Bambu-Drucker gefunden (gesucht in {', '.join(n + '.x' for n in netze)})"
    for ip in treffer:
        ok, _ = lan_pruefen(ip, code)
        if ok:
            return ip, f"Gefunden unter {ip}"
    return "", f"{len(treffer)} Drucker gefunden, aber keiner nimmt diesen Zugangscode an"


def farbabstand(a, b):
    a, b = _farbe(a), _farbe(b)
    if not a or not b:
        return 0
    return sum((int(a[i:i + 2], 16) - int(b[i:i + 2], 16)) ** 2 for i in (1, 3, 5))


def _lab(h):
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (1, 3, 5))
    f = lambda c: c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = f(r), f(g), f(b)
    x = (r * 0.4124 + g * 0.3576 + b * 0.1805) / 0.95047
    y = r * 0.2126 + g * 0.7152 + b * 0.0722
    z = (r * 0.0193 + g * 0.1192 + b * 0.9505) / 1.08883
    t = lambda v: v ** (1 / 3) if v > 0.008856 else 7.787 * v + 16 / 116
    return 116 * t(y) - 16, 500 * (t(x) - t(y)), 200 * (t(y) - t(z))


def farbunterschied(a, b):
    """Farbabstand wie das Auge ihn sieht (CIEDE2000, Helligkeit halb gewichtet): Grau bleibt Grau, egal wie hell.
    Etwa: 0–10 gleiche Farbe, bis 20 ähnlich, darüber andere Farbe. Fehlt eine Farbe: 0."""
    import math
    a, b = _farbe(a), _farbe(b)
    if not a or not b:
        return 0
    L1, a1, b1 = _lab(a)
    L2, a2, b2 = _lab(b)
    cm = (math.hypot(a1, b1) + math.hypot(a2, b2)) / 2
    g = 0.5 * (1 - math.sqrt(cm ** 7 / (cm ** 7 + 25 ** 7)))
    a1p, a2p = a1 * (1 + g), a2 * (1 + g)
    c1, c2 = math.hypot(a1p, b1), math.hypot(a2p, b2)
    h1, h2 = math.degrees(math.atan2(b1, a1p)) % 360, math.degrees(math.atan2(b2, a2p)) % 360
    dl, dc = L2 - L1, c2 - c1
    if c1 * c2 == 0:
        dh, hm = 0, h1 + h2
    else:
        d = h2 - h1
        dh = d if abs(d) <= 180 else (d - 360 if d > 180 else d + 360)
        hm = (h1 + h2) / 2 if abs(h1 - h2) <= 180 else ((h1 + h2 + 360) / 2 if h1 + h2 < 360 else (h1 + h2 - 360) / 2)
    dH = 2 * math.sqrt(c1 * c2) * math.sin(math.radians(dh / 2))
    lm, cpm = (L1 + L2) / 2, (c1 + c2) / 2
    t = (1 - 0.17 * math.cos(math.radians(hm - 30)) + 0.24 * math.cos(math.radians(2 * hm))
         + 0.32 * math.cos(math.radians(3 * hm + 6)) - 0.20 * math.cos(math.radians(4 * hm - 63)))
    sl = 1 + 0.015 * (lm - 50) ** 2 / math.sqrt(20 + (lm - 50) ** 2)
    sc, sh = 1 + 0.045 * cpm, 1 + 0.015 * cpm * t
    rt = -math.sin(math.radians(2 * 30 * math.exp(-((hm - 275) / 25) ** 2))) * 2 * math.sqrt(cpm ** 7 / (cpm ** 7 + 25 ** 7))
    return math.sqrt(max(0.0, (dl / (2 * sl)) ** 2 + (dc / sc) ** 2 + (dH / sh) ** 2 + rt * (dc / sc) * (dH / sh)))


FARB_TOL = 20  # bis hierhin gilt eine Fachfarbe als dieselbe Sorte


def cloud_anfrage(token, region, pfad, timeout=20):
    req = urllib.request.Request(CLOUD_API.get(region, CLOUD_API["global"]) + pfad,
                                 headers=dict(KOPF, Authorization="Bearer " + token))
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8") or "{}")


def cloud_uid(token, region):
    for pfad in ("/v1/design-user-service/my/preference", "/v1/user-service/my/profile"):
        try:
            d = cloud_anfrage(token, region, pfad)
        except Exception:
            continue
        uid = d.get("uid") or d.get("uidStr") or (d.get("user") or {}).get("uid")
        if uid:
            return str(uid)
    raise RuntimeError("Bambu-Cloud: Benutzer-ID nicht abrufbar (Anmeldung abgelaufen?)")


def cloud_geraete(token, region):
    d = cloud_anfrage(token, region, "/v1/iot-service/api/user/bind")
    out = []
    for g in d.get("devices") or []:
        out.append({"serial": g.get("dev_id"), "name": g.get("name") or "", "produkt": g.get("dev_product_name") or "",
                    "modell": modell_aus_serie(g.get("dev_id"), g.get("dev_product_name")), "online": bool(g.get("online")),
                    "code": g.get("dev_access_code") or ""})
    return out


def cloud_aufgabe(token, region, serial, task_id="", titel=""):
    d = cloud_anfrage(token, region, "/v1/user-service/my/tasks?" + urllib.parse.urlencode({"deviceId": serial, "limit": 5}))
    hits = d.get("hits") or []
    for h in hits:
        if task_id and str(h.get("id")) == str(task_id):
            return h
    for h in hits:
        if titel and titel in (h.get("title") or "", h.get("designTitle") or ""):
            return h
    return hits[0] if hits else None


def fehlertext(e):
    if isinstance(e, (socket.timeout, TimeoutError)):
        return "nicht erreichbar (Zeitüberschreitung) – IP-Adresse prüfen, Drucker an?"
    if isinstance(e, ConnectionRefusedError):
        return "Verbindung abgelehnt – am Drucker den LAN-Modus einschalten"
    if isinstance(e, socket.gaierror):
        return "Adresse unbekannt"
    if isinstance(e, ssl.SSLError):
        return "TLS-Fehler: " + str(e)
    if isinstance(e, OSError) and getattr(e, "errno", None) in (113, 101, 65):
        return "Netz nicht erreichbar – liegt der Drucker im selben Netz wie die Synology?"
    return str(e) or e.__class__.__name__


# ---------------------------------------------------------------- Verbindung je Drucker

class Drucker:
    def __init__(self, d, wirt):
        self.d = d
        self.wirt = wirt
        self.p = {}
        self.module = []
        self.online = False
        self.fehler = ""
        self.zuletzt = 0
        self.vorher = None
        self.auftrag = None
        self.client = None
        self.stop = threading.Event()
        self.thread = None

    @property
    def serial(self):
        return str(self.d.get("serial") or "").strip()

    def info(self):
        p = self.p
        return {"id": self.d.get("id"), "name": self.d.get("name") or MODELL_NAMEN.get(self.d.get("modell") or "", ""),
                "serial": self.serial, "modus": self.d.get("modus"), "praefix": praefix(self.d), "online": self.online,
                "fehler": self.fehler, "status": str(p.get("gcode_state") or ""), "fortschritt": _int(p.get("mc_percent"), 0),
                "restzeit": _int(p.get("mc_remaining_time"), 0), "aufgabe": p.get("subtask_name") or "",
                "zuletzt": self.zuletzt, "faecher": [f for f in faecher(p)]}

    # ---- MQTT
    def starten(self):
        self.thread = threading.Thread(target=self._lauf, name="drucker-" + self.serial, daemon=True)
        self.thread.start()

    def beenden(self):
        self.stop.set()
        try:
            if self.client:
                self.client.disconnect()
        except Exception:
            pass

    def _zugang(self):
        if self.d.get("modus") == "cloud":
            c = self.wirt.cloud()
            if not c.get("token"):
                raise RuntimeError("Bambu-Cloud: nicht angemeldet")
            if not c.get("uid"):
                c["uid"] = cloud_uid(c["token"], c.get("region", "global"))
                self.wirt.cloud_merken(c)
            return CLOUD_MQTT.get(c.get("region", "global"), CLOUD_MQTT["global"]), "u_" + c["uid"], c["token"], True
        if not self.d.get("ip") or not self.d.get("code"):
            raise RuntimeError("IP-Adresse oder Zugangscode fehlt")
        return self.d["ip"], "bblp", self.d["code"], False

    def _lauf(self):
        warten = 5
        while not self.stop.is_set():
            try:
                host, user, pw, pruefen = self._zugang()
                c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="schichtlohn-" + uuid.uuid4().hex[:8], protocol=mqtt.MQTTv311)
                c.username_pw_set(user, pw)
                if pruefen:
                    c.tls_set(cert_reqs=ssl.CERT_REQUIRED)
                else:
                    c.tls_set(cert_reqs=ssl.CERT_NONE)
                    c.tls_insecure_set(True)
                c.on_connect = self._verbunden
                c.on_message = self._nachricht
                c.on_disconnect = self._getrennt
                self.client = c
                c.connect(host, 8883, keepalive=30)
                letzter_push = 0
                t0 = time.time()
                war_verbunden = False
                while not self.stop.is_set():
                    rc = c.loop(timeout=1.0)
                    if c.is_connected():
                        if not war_verbunden:
                            war_verbunden, warten = True, 5
                    elif war_verbunden or rc not in (0, mqtt.MQTT_ERR_SUCCESS) or time.time() - t0 > 20:
                        if not war_verbunden and not self.fehler:
                            self.fehler = "Drucker antwortet nicht (Adresse, Zugangscode, LAN-Modus prüfen)"
                        break
                    if self.online and time.time() - letzter_push > 300:
                        self._pushall()
                        letzter_push = time.time()
                    if self.online and time.time() - self.zuletzt > 120:
                        raise RuntimeError("keine Meldungen mehr vom Drucker")
            except Exception as e:
                self.fehler = fehlertext(e)
                self.wirt.log(f"Drucker {self.serial}: {self.fehler}")
            self._offline()
            self.stop.wait(warten)
            warten = min(warten * 2, 120)

    def druck_starten(self, name, platte, zuordnung, zeitraffer=False, kalibrieren=True):
        """Startbefehl wie Bambu Studio (LAN): Datei liegt im Hauptverzeichnis. zuordnung = {filament_id (1-basiert): fach_global}"""
        if not (self.client and self.online):
            raise RuntimeError("Drucker ist nicht verbunden")
        if str(self.p.get("gcode_state") or "").upper() in LAUFEND:
            raise RuntimeError("Drucker druckt gerade")
        n = max(zuordnung) if zuordnung else 0
        mapping, mapping2 = [], []
        for i in range(1, n + 1):
            g = zuordnung.get(i)
            if g is None:
                mapping.append(-1)
                mapping2.append({"ams_id": 255, "slot_id": 255})
            elif g >= 254:  # externe Spule
                mapping.append(g)
                mapping2.append({"ams_id": 255 if g == 254 else 254, "slot_id": 0})
            elif g >= 128:  # AMS HT: eigene ID, ein Fach
                mapping.append(g)
                mapping2.append({"ams_id": g, "slot_id": 0})
            else:
                mapping.append(g)
                mapping2.append({"ams_id": g // 4, "slot_id": g % 4})
        nutzt_ams = any(m >= 0 and m < 254 for m in mapping)
        titel = re.sub(r"(\.gcode)?\.3mf$", "", name, flags=re.I)
        befehl = {"print": {"sequence_id": str(int(time.time()) % 100000), "command": "project_file", "param": f"Metadata/plate_{int(platte)}.gcode",
                            "project_id": "0", "profile_id": "0", "task_id": "0", "subtask_id": "0", "subtask_name": titel,
                            "file": name, "url": f"ftp:///{name}", "md5": "", "timelapse": bool(zeitraffer), "bed_type": "auto",
                            "bed_levelling": bool(kalibrieren), "bed_leveling": bool(kalibrieren), "auto_bed_leveling": 1 if kalibrieren else 0,
                            "flow_cali": False, "vibration_cali": bool(kalibrieren), "layer_inspect": False,
                            "ams_mapping": mapping, "ams_mapping2": mapping2, "use_ams": nutzt_ams, "cfg": "0",
                            "extrude_cali_flag": 0, "nozzle_offset_cali": 2}}
        self.client.publish(f"device/{self.serial}/request", json.dumps(befehl))
        self.wirt.log(f"Drucker {self.serial}: Druck gestartet: {name} Platte {platte}, AMS {mapping}")
        return befehl["print"]

    def stoppen(self):
        """Druck abbrechen wie am Display (Heizungen aus, Lüfter laufen weiter)."""
        if not (self.client and self.online):
            raise RuntimeError("Drucker ist nicht verbunden")
        self.client.publish(f"device/{self.serial}/request", json.dumps({"print": {"sequence_id": str(int(time.time()) % 100000), "command": "stop", "param": ""}}))
        self.wirt.log(f"Drucker {self.serial}: NOTAUS – Druck gestoppt")

    def fach_setzen(self, fach, fid, farbe, typ, tmin, tmax):
        """Filament eines AMS-Fachs festlegen (wie „Fach bearbeiten“ in Bambu Studio). fach = Eintrag aus faecher()."""
        if not (self.client and self.online):
            raise RuntimeError("Drucker ist nicht verbunden")
        g = fach["global"]
        if fach["ams"] is None:  # externe Spule
            ams_id, slot, tray = (255 if g == 254 else 254), 0, 254
        elif g >= 128:  # AMS HT: ein Fach je Einheit
            ams_id, slot, tray = fach["ams"], 0, fach["ams"]
        else:
            ams_id, slot, tray = fach["ams"], fach["fach"], fach["ams"] * 4 + fach["fach"]
        f = str(farbe or "#888888").lstrip("#").upper()
        f = (f + "FF") if len(f) == 6 else (f if len(f) == 8 else "888888FF")
        befehl = {"print": {"sequence_id": str(int(time.time()) % 100000), "command": "ams_filament_setting", "ams_id": ams_id, "slot_id": slot,
                            "tray_id": tray, "tray_info_idx": fid, "tray_color": f, "tray_type": typ,
                            "nozzle_temp_min": int(tmin), "nozzle_temp_max": int(tmax), "setting_id": "", "reason": "success", "result": "success"}}
        self.client.publish(f"device/{self.serial}/request", json.dumps(befehl))
        self.wirt.log(f"Drucker {self.serial}: {fach['ort']} auf {typ} {fid} #{f[:6]} gesetzt")
        threading.Timer(2.0, self._pushall).start()
        return befehl["print"]

    def _pushall(self):
        try:
            self.client.publish(f"device/{self.serial}/request",
                                json.dumps({"pushing": {"sequence_id": "0", "command": "pushall", "version": 1, "push_target": 1}}))
        except Exception:
            pass

    def _verbunden(self, client, userdata, flags, rc, props=None):
        if getattr(rc, "is_failure", False) or (isinstance(rc, int) and rc):
            self.fehler = "Anmeldung abgelehnt (" + str(rc) + ") – Zugangscode bzw. Cloud-Anmeldung prüfen"
            return
        client.subscribe(f"device/{self.serial}/report")
        self.fehler = ""
        self._pushall()
        self._get_version()

    def _get_version(self):
        # Modul-/Versionsliste holen – darin stehen die Seriennummern der AMS-Einheiten (amsSn) für den Filament Manager
        try:
            self.client.publish(f"device/{self.serial}/request",
                                json.dumps({"info": {"sequence_id": "1", "command": "get_version"}}))
        except Exception:
            pass

    def _getrennt(self, *a, **k):
        self._offline()

    def _offline(self):
        if self.online:
            self.online = False
            self.wirt.zustaende(self, zustaende(self.d, self.p, False))

    def _nachricht(self, client, userdata, msg):
        try:
            daten = json.loads(msg.payload.decode("utf-8", "replace"))
        except ValueError:
            return
        self.verarbeiten(daten)

    # ---- Auswertung (auch für Tests direkt aufrufbar)
    def verarbeiten(self, daten):
        info = daten.get("info")
        if isinstance(info, dict) and info.get("command") == "get_version" and isinstance(info.get("module"), list):
            self.module = info["module"]
            self.zuletzt = time.time()
            self.online = True
        p = daten.get("print")
        if not isinstance(p, dict):
            return
        tief_mischen(self.p, p)
        self.zuletzt = time.time()
        self.online = True
        self.fehler = ""
        st = str(self.p.get("gcode_state") or "")
        if st in LAUFEND:
            if not self.auftrag or self.auftrag.get("name") != self.p.get("subtask_name"):
                self.auftrag = {"name": self.p.get("subtask_name") or "", "task": str(self.p.get("task_id") or ""),
                                "start": time.time(), "rest": {f["global"]: (f["rest"], f["gewicht"]) for f in faecher(self.p)},
                                "max": 0, "schicht": 0, "skip": {}, "datei": None, "gcode": None, "objekte": None}
                if self.d.get("ip") and self.d.get("code"):  # auch bei Cloud-Druckern, wenn die IP eingetragen ist
                    threading.Thread(target=self._datei_vorab, daemon=True).start()
            self.auftrag["max"] = max(self.auftrag["max"], _int(self.p.get("mc_percent"), 0))
            self.auftrag["schicht"] = max(self.auftrag.get("schicht", 0), _int(self.p.get("layer_num"), 0) or 0)
            self._skip_merken(self.auftrag)
        if self.vorher in LAUFEND and st in ("FINISH", "FAILED"):
            a = self.auftrag or {"name": self.p.get("subtask_name") or "", "task": str(self.p.get("task_id") or ""),
                                 "rest": {}, "max": _int(self.p.get("mc_percent"), 0), "schicht": _int(self.p.get("layer_num"), 0) or 0,
                                 "skip": {}, "datei": None, "gcode": None, "objekte": None}
            self._skip_merken(a)
            self.auftrag = None
            anteil = 1.0 if st == "FINISH" else min(1.0, max(a.get("max", 0), _int(self.p.get("mc_percent"), 0)) / 100)
            threading.Thread(target=self._abschluss, args=(a, st, anteil, json.loads(json.dumps(self.p))), daemon=True).start()
        if st:
            self.vorher = st
        self.wirt.zustaende(self, zustaende(self.d, self.p, True))

    def _skip_merken(self, a):
        """Am Drucker übersprungene Teile (s_obj) mit Schicht und Fortschritt zum Zeitpunkt des Überspringens merken."""
        liste = self.p.get("s_obj")
        if not isinstance(liste, list):
            return
        for i in liste:
            i = _int(i)
            if i is not None and i not in a["skip"]:
                a["skip"][i] = {"schicht": _int(self.p.get("layer_num"), 0) or 0, "prozent": _int(self.p.get("mc_percent"), 0) or 0}
                self.wirt.log(f"Drucker {self.serial}: Teil {i} übersprungen (Schicht {a['skip'][i]['schicht']}, {a['skip'][i]['prozent']} %)")

    def _datei_auswerten(self, a, daten, platte):
        a["datei"] = slice_info(daten, platte)
        try:
            k = datei_kopf(daten, platte)
            a["vorschau"] = k.get("bild")
            a["minuten_plan"] = k.get("minuten") or 0
        except Exception as e:
            self.wirt.log(f"Drucker {self.serial}: Vorschaubild nicht lesbar: {e}")
        try:
            a["objekte"] = objekte(daten, platte)
        except Exception as e:
            self.wirt.log(f"Drucker {self.serial}: Objekte nicht lesbar: {e}")
        try:
            a["gcode"] = gcode_auswerten(daten, platte)
        except Exception as e:
            self.wirt.log(f"Drucker {self.serial}: G-Code nicht lesbar: {e}")

    def _datei_vorab(self):
        """Gramm schon beim Druckstart aus der Datei lesen (am Ende ist sie evtl. schon überschrieben)."""
        a = self.auftrag
        time.sleep(5)
        try:
            daten, pfad = druckdatei_laden(self.d["ip"], self.d["code"], self.p)
            if daten and a is not None:
                self._datei_auswerten(a, daten, platte_aus(self.p))
                self.wirt.log(f"Drucker {self.serial}: Druckdatei {pfad} gelesen ({len(a['datei'])} Filamente, "
                              f"{len(a.get('objekte') or {})} Teile{', mit G-Code' if a.get('gcode') else ''})")
        except Exception as e:
            self.wirt.log(f"Drucker {self.serial}: Druckdatei nicht lesbar: {e}")

    def _ueberspringen(self, a, st, anteil, datei):
        """Anteil je Filament (Datei-ID), der wirklich gedruckt wurde, wenn Teile übersprungen wurden.
        → (anteile {fid_id: faktor} oder None, genau: bool)"""
        skip = a.get("skip") or {}
        bis = None if st == "FINISH" else (a.get("schicht") or None)
        g = a.get("gcode")
        if g and g["e"] and (skip or bis):
            ids = [fi["id"] for fi in datei]
            if len(ids) == 1:  # ein Filament: alle Werkzeuge zusammenfassen
                zus = {}
                for (s, o, w), mm in g["e"].items():
                    zus[(s, o, 0)] = zus.get((s, o, 0), 0.0) + mm
                g = {"e": zus}
            je_wz = gedruckter_anteil(g, {o: s["schicht"] for o, s in skip.items()}, bis)
            extra = anteil if (st != "FINISH" and bis is None) else 1.0  # Abbruch ohne Schichtangabe: Fortschritt dazu
            if len(ids) == 1:
                return {ids[0]: je_wz.get(0, anteil) * extra}, True
            return {i: je_wz.get(i - 1, anteil) * extra for i in ids}, True
        if not skip:
            return None, True
        # ohne G-Code: jedes Teil gleich schwer annehmen, ab dem Überspringen fehlt sein Rest
        n = len(a.get("objekte") or {})
        if n < 2:
            return None, False
        weg = sum((1 - min(100, s["prozent"]) / 100) / n for s in skip.values())
        return {fi["id"]: max(0.0, anteil - weg) for fi in datei}, False

    def posten(self, a, anteil, p, st="FINISH"):
        """→ (posten, quelle) mit posten = [{gramm, gramm_voll, ort, fid, col, name, material}]"""
        fl = faecher(p)
        # 1) Druckdatei
        datei = a.get("datei")
        if datei is None and self.d.get("ip") and self.d.get("code"):
            try:
                daten, _ = druckdatei_laden(self.d["ip"], self.d["code"], p)
                if daten:
                    self._datei_auswerten(a, daten, platte_aus(p))
                    datei = a["datei"]
            except Exception as e:
                self.wirt.log(f"Drucker {self.serial}: Druckdatei nicht lesbar: {e}")
        if datei:
            faktoren, genau = self._ueberspringen(a, st, anteil, datei)
            a["skip_genau"] = genau
            out = []
            for fi, f in zuordnen(datei, fl):
                fk = faktoren.get(fi["id"], anteil) if faktoren else anteil
                out.append({"gramm": round(fi["gramm"] * fk, 2), "gramm_voll": round(fi["gramm"] * anteil, 2), "gramm_datei": round(fi["gramm"], 2), "ort": f["ort"] if f else "Druckdatei",
                            "fid": (f["fid"] if f and f["fid"] else fi["fid"]), "col": (f["farbe"] if f and f["farbe"] else fi["farbe"]),
                            "name": f["name"] if f else "", "material": (f["typ"] if f else fi["typ"])})
            return out, "Druckdatei"
        a["skip_genau"] = not a.get("skip")
        # 2) Cloud-Aufgabe
        c = self.wirt.cloud()
        if c.get("token"):
            try:
                h = cloud_aufgabe(c["token"], c.get("region", "global"), self.serial, a.get("task"), a.get("name"))
                if h and h.get("amsDetailMapping"):
                    nach_global = {f["global"]: f for f in fl}
                    out = []
                    for m in h["amsDetailMapping"]:
                        g = float(m.get("weight") or 0)
                        if g <= 0:
                            continue
                        f = nach_global.get(_int(m.get("ams"), -1))
                        out.append({"gramm": round(g * anteil, 2), "gramm_datei": round(g, 2), "ort": f["ort"] if f else "AMS",
                                    "fid": (f["fid"] if f and f["fid"] else str(m.get("filamentId") or "")),
                                    "col": (f["farbe"] if f and f["farbe"] else _farbe(m.get("sourceColor") or m.get("targetColor"))),
                                    "name": f["name"] if f else "", "material": f["typ"] if f else str(m.get("filamentType") or "")})
                    if out:
                        return out, "Bambu-Cloud"
            except Exception as e:
                self.wirt.log(f"Drucker {self.serial}: Cloud-Aufgabe nicht abrufbar: {e}")
        # 3) AMS-Restanzeige
        out = []
        for f in fl:
            alt = (a.get("rest") or {}).get(f["global"])
            if not alt or f["leer"] or f["rest"] < 0 or alt[0] is None or alt[0] < 0:
                continue
            gw = f["gewicht"] or alt[1] or 1000
            g = (alt[0] - f["rest"]) / 100 * gw
            if g > 0.5:
                out.append({"gramm": round(g, 1), "ort": f["ort"], "fid": f["fid"], "col": f["farbe"], "name": f["name"], "material": f["typ"]})
        if out:
            a["skip_genau"] = True  # gemessen: übersprungene Teile sind schon drin
        return out, "AMS-Restanzeige"

    def _abschluss(self, a, st, anteil, p):
        try:
            posten, quelle = self.posten(a, anteil, p, st)
        except Exception as e:
            posten, quelle = [], "Fehler: " + str(e)
        anlass = "Druck fertig" if st == "FINISH" else "Druck abgebrochen"
        dauer = int(time.time() - a["start"]) if a.get("start") else 0
        bild = ""
        c = self.wirt.cloud()
        if c.get("token"):  # Vorschaubild des Auftrags für die Handymeldung
            try:
                h = cloud_aufgabe(c["token"], c.get("region", "global"), self.serial, a.get("task"), a.get("name"))
                bild = str((h or {}).get("cover") or "")
            except Exception as e:
                self.wirt.log(f"Drucker {self.serial}: Vorschaubild nicht abrufbar: {e}")
        self.wirt.druckende(self, {"anlass": anlass, "anteil": anteil, "posten": posten, "quelle": quelle,
                                   "aufgabe": a.get("name") or "", "task": a.get("task") or "", "dauer": dauer, "bild": bild,
                                   "uebersprungen": len(a.get("skip") or {}), "skip_genau": bool(a.get("skip_genau", True)),
                                   "start": a.get("start") or 0, "_vorschau": a.get("vorschau")})


class Bambu:
    """Verwaltet alle Drucker. wirt muss bieten: einstellungen(), cloud(), cloud_merken(c), zustaende(dr, z),
    druckende(dr, ergebnis), log(text)."""

    def __init__(self, wirt):
        self.wirt = wirt
        self.drucker = {}
        self.lock = threading.Lock()

    def neu_starten(self):
        with self.lock:
            for dr in self.drucker.values():
                dr.beenden()
            self.drucker = {}
            if mqtt is None:
                self.wirt.log("paho-mqtt fehlt – Drucker-Anbindung aus")
                return
            for d in self.wirt.einstellungen().get("drucker") or []:
                if d.get("aktiv", True) and d.get("serial"):
                    dr = Drucker(dict(d), self.wirt)
                    self.drucker[dr.serial] = dr
                    dr.starten()

    def liste(self):
        return [dr.info() for dr in self.drucker.values()]
