"""Snapmaker U1 direkt anbinden (Moonraker/Klipper im Heimnetz) – ohne Cloud, ohne Home Assistant.

Der U1 hat vier Druckköpfe statt eines AMS. SchichtLohn fragt den Drucker alle 2 Sekunden über die
Moonraker-Schnittstelle ab (http://<IP>/printer/objects/query, Port 80, ab Werk ohne Schlüssel im Heimnetz)
und übersetzt die Werte in dieselbe Form wie eine Bambu-Meldung. Dadurch laufen Lager, Abbuchung,
Druckerübersicht unverändert mit:

  Kopf 1–4   → wie „AMS 1, Fach 1–4“ (Entitäten sensor.u1_<serie>_ams_1_slot_N), angezeigt als „Kopf N“
  Filament   → aus print_task_config (RFID-Chip der Spule oder Auswahl am Display)
  Gramm      → aus der G-Code-Datei (Moonraker-Metadaten „filament_weight“ = „filament used [g]“ je Filament)
  Vorschau   → Vorschaubild aus der G-Code-Datei
"""
import json
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

import drucker as drucker_mod

ZUSTAND = {"standby": "IDLE", "ready": "IDLE", "printing": "RUNNING", "paused": "PAUSE",
           "complete": "FINISH", "cancelled": "FAILED", "error": "FAILED"}
KOEPFE = 4
FELDER = ("filament_vendor", "filament_type", "filament_sub_type", "filament_color_rgba", "filament_exist", "filament_official")
TAKT = 2.0


def ist_snapmaker(d):
    return str(d.get("typ") or "").lower() == "snapmaker" or str(d.get("modell") or "").lower() == "u1"


def _bekannt(v):
    """Snapmaker schreibt für Unbekanntes „NONE“."""
    v = str(v or "").strip()
    return "" if not v or v.upper() == "NONE" else v


def _liste(v, i):
    return v[i] if isinstance(v, list) and i < len(v) else None


def _packen(ist, ziel):
    """Wie die neue Bambu-Firmware: untere 16 Bit Ist-Wert, obere 16 Bit Ziel (ganze Grad)."""
    ist = max(0, int(round(float(ist or 0))))
    ziel = max(0, int(round(float(ziel or 0))))
    return (ziel << 16) | (ist & 0xFFFF)


def meldung(st, dateiinfo=None):
    """Moonraker-Status (result.status) → Bambu-ähnliche Meldung „print“ für drucker.verarbeiten()."""
    ps = st.get("print_stats") or {}
    vs = st.get("virtual_sdcard") or {}
    ds = st.get("display_status") or {}
    th = st.get("toolhead") or {}
    zustand = ZUSTAND.get(str(ps.get("state") or "").lower(), "IDLE")
    wh = st.get("webhooks") or {}
    if str(wh.get("state") or "ready").lower() in ("shutdown", "error"):
        zustand = "FAILED" if zustand in drucker_mod.LAUFEND else zustand
    fortschritt = ds.get("progress") if ds.get("progress") is not None else vs.get("progress")
    try:
        prozent = int(round(float(fortschritt or 0) * 100))
    except (TypeError, ValueError):
        prozent = 0
    if zustand == "FINISH":
        prozent = 100
    datei = str(ps.get("filename") or "")
    titel = re.sub(r"\.(gcode|g|gco)$", "", datei.rsplit("/", 1)[-1], flags=re.I)
    rest = 0
    dauer = float(ps.get("print_duration") or 0)
    plan = float((dateiinfo or {}).get("estimated_time") or 0)
    if zustand in ("RUNNING", "PAUSE") and prozent > 0:
        if plan > 0:
            rest = plan * (1 - prozent / 100)
        elif prozent >= 2:
            rest = dauer / (prozent / 100) - dauer
    info = ps.get("info") if isinstance(ps.get("info"), dict) else {}
    # Druckköpfe: Temperaturen gepackt wie bei H2 (device.extruder.info), aktiver Kopf zusätzlich als nozzle_temper
    koepfe, aktiv = [], str(th.get("extruder") or "extruder")
    for i in range(KOEPFE):
        e = st.get("extruder" if i == 0 else f"extruder{i}")
        if isinstance(e, dict):
            koepfe.append({"id": i, "temp": _packen(e.get("temperature"), e.get("target"))})
    m = re.fullmatch(r"extruder(\d*)", aktiv)
    akt_idx = int(m.group(1) or 0) if m else 0
    akt = st.get(aktiv) if isinstance(st.get(aktiv), dict) else (st.get("extruder") or {})
    bett = st.get("heater_bed") or {}
    # Filament je Kopf
    cfg = st.get("print_task_config") or {}
    trays = []
    for i in range(KOEPFE):
        da = _liste(cfg.get("filament_exist"), i)
        typ = _bekannt(_liste(cfg.get("filament_type"), i))
        unter = _bekannt(_liste(cfg.get("filament_sub_type"), i))
        marke = _bekannt(_liste(cfg.get("filament_vendor"), i))
        farbe = str(_liste(cfg.get("filament_color_rgba"), i) or "").strip().lstrip("#")
        if not re.fullmatch(r"[0-9A-Fa-f]{6}([0-9A-Fa-f]{2})?", farbe):
            farbe = ""
        farbe = (farbe + "FF")[:8].upper() if farbe else ""
        belegt = bool(typ) and da is not False
        name = " ".join(x for x in (marke, typ, unter) if x)
        trays.append({"id": i, "tray_type": typ if belegt else "", "tray_color": farbe if belegt else "",
                      "tray_sub_brands": name if belegt else "", "tray_info_idx": "", "remain": -1, "tray_weight": 0,
                      "tag_uid": "", "official": bool(_liste(cfg.get("filament_official"), i))})
    p = {"gcode_state": zustand, "mc_percent": prozent, "mc_remaining_time": int(round(rest / 60)),
         "subtask_name": titel, "gcode_file": datei, "task_id": "",
         "layer_num": info.get("current_layer") or 0, "total_layer_num": info.get("total_layer") or 0,
         "nozzle_temper": round(float(akt.get("temperature") or 0), 1), "nozzle_target_temper": round(float(akt.get("target") or 0), 1),
         "bed_temper": round(float(bett.get("temperature") or 0), 1), "bed_target_temper": round(float(bett.get("target") or 0), 1),
         "device": {"extruder": {"info": koepfe}},
         "ams": {"ams": [{"id": 0, "tray": trays}], "tray_now": str(akt_idx)},
         "print_error": 1 if str(ps.get("state") or "").lower() == "error" else 0,
         "_kopf": True}
    led = st.get("led cavity_led")
    if isinstance(led, dict) and isinstance(led.get("color_data"), list) and led["color_data"]:
        an = any(float(x or 0) > 0 for x in (led["color_data"][0] or []))
        p["lights_report"] = [{"node": "chamber_light", "mode": "on" if an else "off"}]
    return p


class SnapmakerDrucker(drucker_mod.Drucker):
    """Snapmaker U1 über Moonraker. Gleiche Schnittstelle wie drucker.Drucker (info, p, online, verlauf, letzter …)."""
    snapmaker = True

    def __init__(self, d, wirt):
        super().__init__(d, wirt)
        self.dateiinfo = {}
        self._datei = ""

    def info(self):
        i = super().info()
        i["typ"] = "snapmaker"
        return i

    # ---- Verbindung
    def _basis(self):
        ip = str(self.d.get("ip") or "").strip()
        if not ip:
            raise RuntimeError("IP-Adresse fehlt")
        return ip if ip.startswith("http") else "http://" + ip

    def _anfrage(self, pfad, daten=None, timeout=10, roh=False):
        kopf = {"Accept": "application/json"}
        if self.d.get("code"):  # nur nötig, wenn am Drucker ein Moonraker-Schlüssel eingerichtet ist
            kopf["X-Api-Key"] = str(self.d["code"])
        rumpf = None
        if daten is not None:
            rumpf = json.dumps(daten).encode()
            kopf["Content-Type"] = "application/json"
        req = urllib.request.Request(self._basis() + pfad, data=rumpf, headers=kopf, method="POST" if daten is not None else "GET")
        with urllib.request.urlopen(req, timeout=timeout) as r:
            inhalt = r.read()
        return inhalt if roh else json.loads(inhalt.decode("utf-8", "replace"))

    def _objekte(self):
        q = "&".join(["print_stats", "virtual_sdcard", "display_status", "toolhead", "heater_bed", "webhooks", "led%20cavity_led",
                      "print_task_config=" + ",".join(FELDER)] +
                     ["extruder" if i == 0 else f"extruder{i}" for i in range(KOEPFE)])
        return (self._anfrage("/printer/objects/query?" + q).get("result") or {}).get("status") or {}

    def _lauf(self):
        warten = 5
        while not self.stop.is_set():
            try:
                st = self._objekte()
                warten = 5
                datei = str((st.get("print_stats") or {}).get("filename") or "")
                if datei and datei != self._datei:
                    self._datei = datei
                    self.dateiinfo = self._metadaten(datei) or {}
                self.verarbeiten({"print": meldung(st, self.dateiinfo)})
                self.stop.wait(TAKT)
                continue
            except urllib.error.HTTPError as e:
                self.fehler = ("Drucker verlangt einen Moonraker-Schlüssel (in den Druckereinstellungen eintragen)"
                               if e.code in (401, 403) else f"Drucker meldet Fehler {e.code}")
            except Exception as e:
                self.fehler = drucker_mod.fehlertext(e)
            self.wirt.log(f"Snapmaker {self.serial}: {self.fehler}")
            self._offline()
            self.stop.wait(warten)
            warten = min(warten * 2, 60)

    def beenden(self):
        self.stop.set()

    # ---- Druckdatei
    def _metadaten(self, datei):
        try:
            return self._anfrage("/server/files/metadata?filename=" + urllib.parse.quote(datei)).get("result") or {}
        except Exception as e:
            self.wirt.log(f"Snapmaker {self.serial}: Dateiangaben zu {datei} nicht lesbar: {e}")
            return {}

    def _vorschau(self, meta, datei):
        bilder = [b for b in (meta.get("thumbnails") or []) if isinstance(b, dict) and b.get("relative_path")]
        if not bilder:
            return None
        b = max(bilder, key=lambda x: (x.get("width") or 0) * (x.get("height") or 0))
        ordner = datei.rsplit("/", 1)[0] + "/" if "/" in datei else ""
        try:
            return self._anfrage("/server/files/gcodes/" + urllib.parse.quote(ordner + b["relative_path"]), roh=True, timeout=20)
        except Exception:
            return None

    def _datei_vorab(self):
        """Beim Druckstart: Gramm je Filament und Vorschaubild aus der G-Code-Datei holen."""
        a = self.auftrag
        datei = self._datei or str(self.p.get("gcode_file") or "")
        if a is None or not datei:
            return
        meta = self.dateiinfo or self._metadaten(datei)
        a["datei"] = datei_filamente(meta)
        a["vorschau"] = self._vorschau(meta, datei)
        a["minuten_plan"] = round(float(meta.get("estimated_time") or 0) / 60)
        self.wirt.log(f"Snapmaker {self.serial}: Druckdatei {datei} gelesen ({len(a['datei'])} Filamente)")

    def verarbeiten(self, daten):
        # Druckstart erkennen, bevor die Basisklasse den Auftrag anlegt (sie holt die Datei nur mit Bambu-Zugangscode)
        neu = not self.d.get("code") and str((daten.get("print") or {}).get("gcode_state") or "") in drucker_mod.LAUFEND and \
            (not self.auftrag or self.auftrag.get("name") != (daten.get("print") or {}).get("subtask_name"))
        super().verarbeiten(daten)
        if neu and self.auftrag is not None:
            threading.Thread(target=self._datei_vorab, daemon=True).start()

    def posten(self, a, anteil, p, st="FINISH"):
        fl = drucker_mod.faecher(p)
        datei = a.get("datei")
        if datei is None and (self._datei or p.get("gcode_file")):
            meta = self.dateiinfo or self._metadaten(self._datei or p.get("gcode_file"))
            datei = a["datei"] = datei_filamente(meta)
        a["skip_genau"] = True
        if datei:
            # Filament N der Datei druckt (bei bis zu 4 Filamenten) auf Kopf N – passt das Material nicht, wird geschätzt
            mapping = list(range(KOEPFE))
            out = []
            for fi, f in drucker_mod.zuordnen(datei, fl, mapping):
                out.append({"gramm": round(fi["gramm"] * anteil, 2), "gramm_voll": round(fi["gramm"] * anteil, 2),
                            "gramm_datei": round(fi["gramm"], 2), "ort": f["ort"] if f else "Druckdatei",
                            "fid": "", "col": (f["farbe"] if f and f["farbe"] else fi["farbe"]),
                            "name": f["name"] if f else "", "material": (f["typ"] if f else fi["typ"])})
            return out, "Druckdatei"
        return [], "keine Druckdatei"

    def _abschluss(self, a, st, anteil, p):
        try:
            posten, quelle = self.posten(a, anteil, p, st)
        except Exception as e:
            posten, quelle = [], "Fehler: " + str(e)
        self.wirt.druckende(self, {"anlass": "Druck fertig" if st == "FINISH" else "Druck abgebrochen", "anteil": anteil,
                                   "posten": posten, "quelle": quelle, "aufgabe": a.get("name") or "", "task": "",
                                   "dauer": int(time.time() - a["start"]) if a.get("start") else 0, "bild": "",
                                   "uebersprungen": 0, "skip_genau": True, "start": a.get("start") or 0,
                                   "_vorschau": a.get("vorschau")})

    # ---- Befehle
    def _gcode(self, script):
        if not self.online:
            raise RuntimeError("Drucker ist nicht verbunden")
        self._anfrage("/printer/gcode/script", {"script": script})

    def stoppen(self):
        if not self.online:
            raise RuntimeError("Drucker ist nicht verbunden")
        self._anfrage("/printer/print/cancel", {})
        self.wirt.log(f"Snapmaker {self.serial}: NOTAUS – Druck abgebrochen")

    def licht(self, an):
        self._gcode(f"SET_LED LED=cavity_led WHITE={1 if an else 0}")

    def druck_starten(self, *a, **k):
        raise RuntimeError("Drucke für den Snapmaker U1 bitte aus Snapmaker Orca senden")

    def fach_setzen(self, *a, **k):
        raise RuntimeError("Beim Snapmaker U1 Filament bitte am Drucker-Display einstellen")

    def _pushall(self):
        pass

    def _get_version(self):
        pass


def datei_filamente(meta):
    """Moonraker-Metadaten → [{id, fid, typ, farbe, gramm}] wie slice_info() bei Bambu."""
    gramm = meta.get("filament_weight")
    if isinstance(gramm, (int, float)):
        gramm = [gramm]
    if not isinstance(gramm, list) or not gramm:
        g = float(meta.get("filament_weight_total") or 0)
        gramm = [g] if g > 0 else []
    teile = lambda v: [x.strip() for x in re.split(r"[;,]", str(v or "")) if x.strip()]  # noqa: E731
    typen, farben = teile(meta.get("filament_type")), teile(meta.get("filament_colour"))
    out = []
    for i, g in enumerate(gramm):
        try:
            g = float(g or 0)
        except (TypeError, ValueError):
            continue
        if g > 0:
            out.append({"id": i + 1, "fid": "", "typ": typen[i] if i < len(typen) else "",
                        "farbe": drucker_mod._farbe(farben[i] if i < len(farben) else ""), "gramm": g})
    return out


def pruefen(ip, schluessel="", timeout=6):
    """Antwortet unter der IP ein Snapmaker/Moonraker? → (ok, text, name)"""
    d = SnapmakerDrucker({"ip": ip, "code": schluessel, "serial": "test"}, None)
    try:
        info = d._anfrage("/printer/info", timeout=timeout).get("result") or {}
        st = d._anfrage("/printer/objects/query?print_task_config=filament_type", timeout=timeout)
        u1 = "print_task_config" in ((st.get("result") or {}).get("status") or {})
        name = str(info.get("hostname") or "")
        return True, f"{'Snapmaker U1' if u1 else 'Klipper-Drucker'} unter {ip} erreichbar" + (f" ({name})" if name else ""), name
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            return False, "Drucker verlangt einen Moonraker-Schlüssel", ""
        return False, f"{ip} antwortet mit Fehler {e.code}", ""
    except Exception as e:
        return False, f"{ip} nicht erreichbar ({drucker_mod.fehlertext(e)})", ""
