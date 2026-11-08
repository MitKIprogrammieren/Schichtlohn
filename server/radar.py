"""SchichtRadar – Live-Übersicht aller Bambu-Lab-Drucker aus Home Assistant (ha-bambulab).

Liest mit einer Abfrage alle Zustände aus Home Assistant und baut daraus je Drucker ein kompaktes Paket:
Status, Fortschritt, Düsen, Bett, Kammer, Lüfter, AMS mit Feuchte, Energie und Kosten des laufenden Drucks.
Die Kosten kommen aus dem SchichtLohn-Lager (Preis je kg der passenden Sorte) und dem Strompreis.
"""
import re
import threading
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

import drucker as drucker_mod

LAUFEND = ("running", "pause", "prepare", "slicing", "init")
_lock = threading.Lock()
_cache = {"t": 0.0, "wert": None}
_energie = {}  # (entity, zeitpunkt) -> kWh


def _ok(v):
    return v not in (None, "", "unknown", "unavailable", "none")


def _zahl(v, std=None):
    try:
        return float(str(v).replace(",", "."))
    except (TypeError, ValueError):
        return std


def _farbe(c):
    c = str(c or "")
    return c[:7].lower() if re.fullmatch(r"#[0-9a-fA-F]{6}([0-9a-fA-F]{2})?", c) and not c.upper().endswith("00000000") else ""


def _zeit(v):
    if not _ok(v):
        return None
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        return None


def _fach(s):
    """AMS-Fach / Spule aus einem Zustand der Bambu-Integration."""
    a = s.get("attributes") or {}
    leer = bool(a.get("empty")) or str(a.get("type") or "?") in ("?", "")
    rest = a.get("remain")
    return {"typ": "" if leer else str(a.get("type") or ""), "name": "" if leer else str(a.get("name") or s.get("state") or ""),
            "farbe": "" if leer else _farbe(a.get("color")), "rest": rest if isinstance(rest, (int, float)) and rest >= 0 and a.get("remain_enabled") else None,
            "aktiv": bool(a.get("active")), "leer": leer, "fid": str(a.get("filament_id") or ""), "entity": s.get("entity_id")}


def _energie_bei(ha_anfrage, entity, t):
    """Zählerstand (kWh) eines Energiesensors zum Zeitpunkt t – aus dem Verlauf von Home Assistant."""
    k = (entity, t.isoformat())
    if k in _energie:
        return _energie[k]
    wert = None
    try:
        von = (t - timedelta(minutes=30)).isoformat()
        bis = (t + timedelta(minutes=5)).isoformat()
        r = ha_anfrage(f"/api/history/period/{quote(von)}?filter_entity_id={entity}&end_time={quote(bis)}"
                       "&minimal_response&no_attributes", timeout=15)
        werte = [(_zeit(x.get("last_changed")), _zahl(x.get("state"))) for x in (r[0] if r else [])]
        werte = [(z, w) for z, w in werte if z and w is not None]
        vorher = [w for z, w in werte if z <= t]
        wert = vorher[-1] if vorher else (werte[0][1] if werte else None)
    except Exception as e:
        print("Radar Energieverlauf:", e, flush=True)
        return None
    if len(_energie) > 200:
        _energie.clear()
    _energie[k] = wert
    return wert


def _strom(ha_anfrage, by, ent):
    a = by.get(ent) or {}
    w = _zahl(a.get("state"))
    if w is None:
        return None
    if str((a.get("attributes") or {}).get("unit_of_measurement") or "").lower() == "wh":
        w /= 1000
    return w


def sammeln(ha_anfrage, preis_fn, einst, modell_namen):
    states = ha_anfrage("/api/states", timeout=20)
    by = {s["entity_id"]: s for s in states}
    rad = einst if isinstance(einst, dict) else {}
    zuordnung = rad.get("drucker") if isinstance(rad.get("drucker"), dict) else {}
    strompreis = _zahl(rad.get("strompreis"), 0.35)
    jetzt = datetime.now(timezone.utc)

    praefixe = []
    for eid, s in by.items():
        m = re.fullmatch(r"sensor\.([a-z0-9]+)_([a-z0-9]{15})_druckstatus", eid)
        a = s.get("attributes") or {}
        if m and a.get("quelle") != "schichtlohn" and "options" in a:
            praefixe.append((m.group(1), m.group(2)))

    # Leistungs-/Energiesensoren automatisch zuordnen: sensor.<modell>_power, nur wenn das Modell einmal vorkommt
    anzahl = {}
    for mo, _ in praefixe:
        anzahl[mo] = anzahl.get(mo, 0) + 1

    drucker = []
    for modell, serie in praefixe:
        pre = f"{modell}_{serie}"
        z = lambda suf, d="sensor": (by.get(f"{d}.{pre}_{suf}") or {})
        st = lambda suf, d="sensor": z(suf, d).get("state")
        at = lambda suf, d="sensor": z(suf, d).get("attributes") or {}
        n = lambda suf: _zahl(st(suf)) if _ok(st(suf)) else None
        status = str(st("druckstatus") or "unknown")
        online = st("online", "binary_sensor")
        if online == "off" or status in ("offline", "unavailable"):
            status = "offline"
        cfg = zuordnung.get(pre) if isinstance(zuordnung.get(pre), dict) else {}
        name = cfg.get("name") or (st("name_des_druckers") if _ok(st("name_des_druckers")) else "") or modell_namen.get(modell, modell.upper())

        # Düsen: H2D/H2C/H2S mit zwei Düsen (links/rechts), sonst eine
        duesen = []
        if f"sensor.{pre}_linke_dusentemperatur" in by:
            duesen.append({"id": "L", "name": "Links", "temp": n("linke_dusentemperatur"), "ziel": n("linksdusenzieltemperatur"),
                           "groesse": st("linke_dusengrosse"), "typ": st("linke_dusentyp")})
            duesen.append({"id": "R", "name": "Rechts", "temp": n("rechte_dusentemperatur"), "ziel": n("rechte_dusenzieltemperatur"),
                           "groesse": st("rechte_dusengrosse"), "typ": st("rechte_dusentyp")})
        else:
            duesen.append({"id": "1", "name": "Düse", "temp": n("temperatur_der_duse"), "ziel": n("zieltemperatur_der_duse"),
                           "groesse": st("dusengrosse"), "typ": st("dusentyp")})
        akt = max(range(len(duesen)), key=lambda i: ((duesen[i]["ziel"] or 0), (duesen[i]["temp"] or 0)))
        for i, d in enumerate(duesen):
            d["aktiv"] = i == akt and (d["ziel"] or 0) > 0
            if not _ok(d["groesse"]):
                d["groesse"] = ""
            if not _ok(d["typ"]):
                d["typ"] = ""

        # AMS-Einheiten (auch mit doppeltem Präfix wie sensor.h2c_h2c_<serie>_ams_128_…)
        ams = {}
        muster = re.compile(r"(?:sensor|binary_sensor)\.(?:[a-z0-9]+_)?" + re.escape(pre) + r"_ams_(\d+)_(.+)")
        for eid, s in by.items():
            m = muster.fullmatch(eid)
            if not m:
                continue
            nr, rest = int(m.group(1)), m.group(2)
            u = ams.setdefault(nr, {"nr": nr, "name": f"AMS HT {nr - 127}" if nr >= 128 else f"AMS {nr}", "ht": nr >= 128, "faecher": {}})
            fm = re.fullmatch(r"slot_(\d+)(?:_2)?", rest)
            if fm:
                f = _fach(s)
                f["ort"] = u["name"] if nr >= 128 else f"AMS {nr} Fach {fm.group(1)}"
                u["faecher"][int(fm.group(1))] = f
            elif rest == "luftfeuchtigkeit":
                u["feuchte"] = _zahl(s.get("state"))
            elif rest == "index_der_luftfeuchtigkeit":
                u["feuchte_stufe"] = _zahl(s.get("state"))
            elif rest == "temperatur":
                u["temp"] = _zahl(s.get("state"))
            elif rest == "trocknen":
                u["trocknet"] = s.get("state") == "on"
            elif rest == "verbleibende_trocknungszeit":
                w = _zahl(s.get("state"))
                einheit = str((s.get("attributes") or {}).get("unit_of_measurement") or "min").lower()
                u["trocken_rest"] = None if w is None else round(w * 60 if einheit == "h" else w / 60 if einheit == "s" else w)
        ams_liste = []
        for nr in sorted(ams):
            u = ams[nr]
            u["faecher"] = [u["faecher"][k] for k in sorted(u["faecher"])]
            ams_liste.append(u)
        extern = []
        for i, suf in enumerate(("externalspool_externe_spule", "externalspool2_externe_spule")):
            s = by.get(f"sensor.{pre}_{suf}")
            if s:
                f = _fach(s)
                f["ort"] = "Externe Spule" + (" 2" if i else "")
                extern.append(f)

        # Aktives Filament
        aktiv = None
        for f in [f for u in ams_liste for f in u["faecher"]] + extern:
            if f["aktiv"] and not f["leer"]:
                aktiv = f
        if not aktiv:
            a = at("aktiver_slot")
            if _ok(st("aktiver_slot")) and st("aktiver_slot") != "?":
                aktiv = {"typ": str(a.get("type") or ""), "name": str(a.get("name") or st("aktiver_slot")), "farbe": _farbe(a.get("color")), "ort": ""}

        laeuft = status in LAUFEND
        pct = n("druckfortschritt") or 0
        start, ende = _zeit(st("startzeit")), _zeit(st("endzeit"))
        rest_h = n("verbleibende_zeit")

        # Verbrauch laut Druckdatei je Fach + Kosten aus dem Lager
        gew_attr, len_attr = at("gewicht_des_drucks"), at("drucklange")
        anteil = 1.0 if status == "finish" else max(0.0, min(1.0, pct / 100))
        alle = {f["ort"]: f for u in ams_liste for f in u["faecher"]}
        for f in extern:
            alle[f["ort"]] = f
        posten, fil_kosten, fehlt = [], 0.0, False
        aufgabe = st("name_der_aufgabe") if _ok(st("name_der_aufgabe")) else ""
        wartung = drucker_mod.ist_wartung(re.sub(r"\.(gcode|3mf)$", "", aufgabe.rsplit("/", 1)[-1]))
        for k, g in ({} if wartung or not (laeuft or status in ("finish", "failed")) else gew_attr).items():
            g = _zahl(g)
            if g is None or g <= 0 or k in ("state_class", "unit_of_measurement", "device_class", "friendly_name", "icon"):
                continue
            mt = re.fullmatch(r"AMS (\d+) Tray (\d+)", k)
            mh = re.fullmatch(r"AMS HT (\d+)", k)
            ort = (f"AMS {mt.group(1)} Fach {mt.group(2)}" if mt else f"AMS HT {mh.group(1)}" if mh
                   else "Externe Spule 2" if k == "External Spool 2" else "Externe Spule" if k.startswith("External") else k)
            f = alle.get(ort) or {}
            preis = preis_fn(f.get("fid") or "", f.get("farbe") or "", name, ort) if f else None
            bisher = g * anteil
            if preis:
                fil_kosten += bisher / 1000 * preis
            else:
                fehlt = True
            posten.append({"ort": ort, "gramm": round(g, 2), "bisher": round(bisher, 2), "meter": round(_zahl(len_attr.get(k), 0) or 0, 2),
                           "typ": f.get("typ") or "", "name": f.get("name") or "", "farbe": f.get("farbe") or "", "preis": preis})

        # Energie
        lei_ent = cfg.get("leistung") or (f"sensor.{modell}_power" if anzahl[modell] == 1 and f"sensor.{modell}_power" in by else "")
        en_ent = cfg.get("energie") or (f"sensor.{modell}_energy" if anzahl[modell] == 1 and f"sensor.{modell}_energy" in by else "")
        leistung = _zahl((by.get(lei_ent) or {}).get("state")) if lei_ent else None
        kwh_druck = None
        if en_ent and start and not wartung and (jetzt - start) < timedelta(days=4) and (laeuft or status in ("finish", "failed")):
            a0 = _energie_bei(ha_anfrage, en_ent, start)
            a1 = _strom(ha_anfrage, by, en_ent) if laeuft or not ende else _energie_bei(ha_anfrage, en_ent, ende)
            if a0 is not None and a1 is not None:
                kwh_druck = max(0.0, a1 - a0)
                if kwh_druck > 30:  # Zählerwechsel o. ä.
                    kwh_druck = None
        strom_kosten = kwh_druck * strompreis if kwh_druck is not None else None
        gesamt = round(fil_kosten + (strom_kosten or 0), 2) if posten or strom_kosten else None

        kam = by.get(f"camera.{pre}_kamera")
        bild = by.get(f"image.{pre}_titelbild")
        licht = by.get(f"light.{pre}_druckraumbeleuchtung")
        drucker.append({
            "pre": pre, "serie": serie.upper(), "modell": modell_namen.get(modell, modell.upper()), "modell_id": modell,
            "name": name, "status": status, "schritt": st("aktueller_arbeitsschritt") if _ok(st("aktueller_arbeitsschritt")) else "",
            "fehler": st("hms_fehler", "binary_sensor") == "on" or st("druckfehler", "binary_sensor") == "on",
            "tuer": st("gehausetur", "binary_sensor") if _ok(st("gehausetur", "binary_sensor")) else None,
            "fortschritt": pct, "rest_min": round(rest_h * 60) if rest_h is not None else None,
            "start": start.isoformat() if start else None, "ende": ende.isoformat() if ende else None,
            "aufgabe": aufgabe, "wartung": wartung,
            "datei": st("gcode_dateiname") if _ok(st("gcode_dateiname")) else "",
            "schicht": n("aktuelle_schicht"), "schichten": n("gesamtzahl_der_schichten"),
            "laufzeit_h": n("gesamtnutzung"), "gewicht": n("gewicht_des_drucks"), "laenge": n("drucklange"),
            "bett": n("druckbetttemperatur"), "bett_ziel": n("zieltemperatur_vom_druckbett"),
            "kammer": n("temperatur_im_druckraum"), "kammer_ziel": n("zieltemperatur_der_kammer"),
            "luefter": {k: n(e) for k, e in (("bauteil", "bauteillufterdrehzahl"), ("druckraum", "druckraumlufterdrehzahl"),
                                              ("druckkopf", "druckkopflufterdrehzahl"), ("hotend", "hotendlufterdrehzahl")) if f"sensor.{pre}_{e}" in by},
            "profil": st("geschwindigkeitsprofil") if _ok(st("geschwindigkeitsprofil")) else "",
            "platte": st("druckbett_typ") if _ok(st("druckbett_typ")) else "",
            "wlan": st("wi_fi_signalqualitat") if _ok(st("wi_fi_signalqualitat")) else "",
            "duesen": duesen, "ams": ams_liste, "extern": extern, "filament": aktiv,
            "kamera": bool(kam) and (kam.get("state") not in ("unavailable",)),
            "bild": (bild.get("last_updated") or "1") if bild and _ok(bild.get("state")) else "",
            "licht": (licht.get("state") == "on") if licht else None,
            "energie": {"leistung": leistung, "leistung_ent": lei_ent, "energie_ent": en_ent,
                        "kwh_druck": round(kwh_druck, 3) if kwh_druck is not None else None,
                        "strom": round(strom_kosten, 2) if strom_kosten is not None else None,
                        "filament": round(fil_kosten, 2) if posten else None, "filament_unvollstaendig": fehlt,
                        "gesamt": gesamt, "strompreis": strompreis},
            "posten": posten,
        })
    reihe = rad.get("reihenfolge") if isinstance(rad.get("reihenfolge"), list) else []
    drucker.sort(key=lambda d: (reihe.index(d["pre"]) if d["pre"] in reihe else 99, d["status"] not in LAUFEND, d["name"].lower()))
    aus = {k for k, v in zuordnung.items() if isinstance(v, dict) and v.get("aus")}
    kandidaten = sorted(
        [{"id": e, "name": (s.get("attributes") or {}).get("friendly_name") or e,
          "art": "energie" if (s.get("attributes") or {}).get("device_class") == "energy" else "leistung"}
         for e, s in by.items() if e.startswith("sensor.") and (s.get("attributes") or {}).get("device_class") in ("power", "energy")],
        key=lambda x: x["name"].lower())
    return {"zeit": time.time(), "drucker": [d for d in drucker if d["pre"] not in aus],
            "ausgeblendet": sorted(aus), "sensoren": kandidaten, "strompreis": strompreis}


def holen(ha_anfrage, preis_fn, einst, modell_namen, max_alter=2.5):
    with _lock:
        if _cache["wert"] is None or time.time() - _cache["t"] > max_alter:
            _cache["wert"] = sammeln(ha_anfrage, preis_fn, einst, modell_namen)
            _cache["t"] = time.time()
        return _cache["wert"]


def leeren():
    with _lock:
        _cache["t"] = 0.0


def verlauf(ha_anfrage, pre, minuten=15):
    """Temperaturverlauf der letzten Minuten: Bett, Düse(n), Kammer."""
    pre = re.sub(r"[^a-z0-9_]", "", pre)
    namen = [("bett", "druckbetttemperatur"), ("duese", "temperatur_der_duse"), ("links", "linke_dusentemperatur"),
             ("rechts", "rechte_dusentemperatur"), ("kammer", "temperatur_im_druckraum")]
    ents = ",".join(f"sensor.{pre}_{e}" for _, e in namen)
    von = (datetime.now(timezone.utc) - timedelta(minutes=max(1, min(int(minuten), 24 * 60)))).isoformat()
    r = ha_anfrage(f"/api/history/period/{quote(von)}?filter_entity_id={ents}&minimal_response&no_attributes", timeout=20) or []
    out = {}
    zu = {f"sensor.{pre}_{e}": k for k, e in namen}
    for reihe in r:
        if not reihe:
            continue
        k = zu.get(reihe[0].get("entity_id"))
        if not k:
            continue
        pkt = []
        for x in reihe:
            t, w = _zeit(x.get("last_changed")), _zahl(x.get("state"))
            if t and w is not None:
                pkt.append([round(t.timestamp()), round(w, 1)])
        if pkt:
            out[k] = pkt[-400:]
    return {"von": von, "reihen": out}
