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
    platten = root.findall("plate")
    if not platten:
        return []
    wahl = platten[0]
    if platte is not None:
        for pl in platten:
            idx = next((m.get("value") for m in pl.findall("metadata") if m.get("key") == "index"), None)
            if _int(idx) == platte:
                wahl = pl
                break
    out = []
    for f in wahl.findall("filament"):
        g = float(f.get("used_g") or 0)
        if g > 0:
            out.append({"id": _int(f.get("id"), 0), "fid": f.get("tray_info_idx") or "", "typ": f.get("type") or "",
                        "farbe": _farbe(f.get("color")), "gramm": g})
    return out


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


def farbabstand(a, b):
    a, b = _farbe(a), _farbe(b)
    if not a or not b:
        return 0
    return sum((int(a[i:i + 2], 16) - int(b[i:i + 2], 16)) ** 2 for i in (1, 3, 5))


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
                                "max": 0, "datei": None}
                if self.d.get("modus") != "cloud" and self.d.get("ip") and self.d.get("code"):
                    threading.Thread(target=self._datei_vorab, daemon=True).start()
            self.auftrag["max"] = max(self.auftrag["max"], _int(self.p.get("mc_percent"), 0))
        if self.vorher in LAUFEND and st in ("FINISH", "FAILED"):
            a = self.auftrag or {"name": self.p.get("subtask_name") or "", "task": str(self.p.get("task_id") or ""),
                                 "rest": {}, "max": _int(self.p.get("mc_percent"), 0), "datei": None}
            self.auftrag = None
            anteil = 1.0 if st == "FINISH" else min(1.0, max(a.get("max", 0), _int(self.p.get("mc_percent"), 0)) / 100)
            threading.Thread(target=self._abschluss, args=(a, st, anteil, json.loads(json.dumps(self.p))), daemon=True).start()
        if st:
            self.vorher = st
        self.wirt.zustaende(self, zustaende(self.d, self.p, True))

    def _datei_vorab(self):
        """Gramm schon beim Druckstart aus der Datei lesen (am Ende ist sie evtl. schon überschrieben)."""
        a = self.auftrag
        time.sleep(5)
        try:
            daten, pfad = druckdatei_laden(self.d["ip"], self.d["code"], self.p)
            if daten and a is not None:
                a["datei"] = slice_info(daten, platte_aus(self.p))
                self.wirt.log(f"Drucker {self.serial}: Druckdatei {pfad} gelesen ({len(a['datei'])} Filamente)")
        except Exception as e:
            self.wirt.log(f"Drucker {self.serial}: Druckdatei nicht lesbar: {e}")

    def posten(self, a, anteil, p):
        """→ (posten, quelle) mit posten = [{gramm, ort, fid, col, name, material}]"""
        fl = faecher(p)
        # 1) Druckdatei
        datei = a.get("datei")
        if datei is None and self.d.get("modus") != "cloud" and self.d.get("ip"):
            try:
                daten, _ = druckdatei_laden(self.d["ip"], self.d["code"], p)
                datei = slice_info(daten, platte_aus(p)) if daten else None
            except Exception as e:
                self.wirt.log(f"Drucker {self.serial}: Druckdatei nicht lesbar: {e}")
        if datei:
            out = []
            for fi, f in zuordnen(datei, fl):
                out.append({"gramm": round(fi["gramm"] * anteil, 2), "ort": f["ort"] if f else "Druckdatei",
                            "fid": (f["fid"] if f and f["fid"] else fi["fid"]), "col": (f["farbe"] if f and f["farbe"] else fi["farbe"]),
                            "name": f["name"] if f else "", "material": (f["typ"] if f else fi["typ"])})
            return out, "Druckdatei"
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
                        out.append({"gramm": round(g * anteil, 2), "ort": f["ort"] if f else "AMS",
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
        return out, "AMS-Restanzeige"

    def _abschluss(self, a, st, anteil, p):
        try:
            posten, quelle = self.posten(a, anteil, p)
        except Exception as e:
            posten, quelle = [], "Fehler: " + str(e)
        anlass = "Druck fertig" if st == "FINISH" else "Druck abgebrochen"
        self.wirt.druckende(self, {"anlass": anlass, "anteil": anteil, "posten": posten, "quelle": quelle,
                                   "aufgabe": a.get("name") or "", "task": a.get("task") or ""})


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
