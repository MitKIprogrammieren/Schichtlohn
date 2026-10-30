#!/usr/bin/env python3
"""Druckwerte aus den Filamentprofilen von OrcaSlicer (AGPL-3.0, enthält die Bambu-Studio-Profile).

Liest resources/profiles/*/filament/**.json, löst die Vererbung („inherits“) auf und schreibt je Profil:
Marke, Material, Name, Düse min/max, Bett min/max, Flow, Pressure Advance (K), max. Volumenstrom.

Aufruf:  python3 tools/slicerwerte.py <pfad-orcaslicer-repo> [ausgabe.json]
Ausgabe: tools/slicerwerte.json  {"stand", "quelle", "profile": [[marke, material, name, d1, d2, b1, b2, flow, k, mvs], …],
                                   "material": {MATERIAL: [d1, d2, b1, b2, flow, k, mvs]}}
"""
import datetime
import glob
import json
import os
import re
import statistics
import sys

FELDER = ("filament_vendor", "filament_type", "nozzle_temperature_range_low", "nozzle_temperature_range_high",
          "nozzle_temperature", "hot_plate_temp", "textured_plate_temp", "filament_flow_ratio",
          "pressure_advance", "enable_pressure_advance", "filament_max_volumetric_speed")
# bevorzugte Druckervariante je Profil (0,4-mm-Düse); X1C zuerst – der Nutzer druckt auf Bambu
VORZUG = ("@BBL X1C", "@BBL H2D", "@BBL P1P", "@BBL A1", "@base", "@System")


def erster(v):
    if isinstance(v, list):
        v = v[0] if v else None
    if v in (None, "", "nil"):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return v


def laden(ordner):
    profile = {}
    for p in glob.glob(os.path.join(ordner, "filament", "**", "*.json"), recursive=True):
        try:
            d = json.load(open(p, encoding="utf-8"))
        except (ValueError, OSError):
            continue
        if d.get("name"):
            profile[d["name"]] = d
    return profile


def aufloesen(name, eigene, gemeinsam, tiefe=0):
    d = eigene.get(name) or gemeinsam.get(name)
    if d is None or tiefe > 12:
        return {}
    basis = aufloesen(d["inherits"], eigene, gemeinsam, tiefe + 1) if d.get("inherits") else {}
    for inc in d.get("include", []) or []:
        basis = {**aufloesen(inc, eigene, gemeinsam, tiefe + 1), **basis}
    return {**basis, **{k: v for k, v in d.items() if k in FELDER}}


def kurzname(name):
    n = re.sub(r"\s*@.*$", "", name).strip()
    return re.sub(r"\s+", " ", n)


def vorzug(name):
    for i, v in enumerate(VORZUG):
        if v in name and "nozzle" not in name.replace(v, ""):
            return i
    return len(VORZUG) + (5 if "nozzle" in name else 0)


def main():
    repo = sys.argv[1]
    aus = sys.argv[2] if len(sys.argv) > 2 else os.path.join(os.path.dirname(os.path.abspath(__file__)), "slicerwerte.json")
    wurzel = os.path.join(repo, "resources", "profiles")
    gemeinsam = {}
    for g in ("OrcaFilamentLibrary", "BBL"):
        gemeinsam.update(laden(os.path.join(wurzel, g)))
    beste = {}  # (marke, material, name) → (vorzug, werte)
    for ordner in sorted(glob.glob(os.path.join(wurzel, "*"))):
        if not os.path.isdir(ordner):
            continue
        eigene = laden(ordner)
        for name, d in eigene.items():
            if str(d.get("instantiation", "")).lower() != "true":
                continue
            w = aufloesen(name, eigene, gemeinsam)
            marke = str(erster(w.get("filament_vendor")) or "").strip()
            material = str(erster(w.get("filament_type")) or "").strip().upper()
            if not marke or not material or marke.lower() in ("generic", "orcaslicer", "custom"):
                marke = marke if marke and marke.lower() not in ("orcaslicer", "custom") else "Generic"
            d1, d2 = erster(w.get("nozzle_temperature_range_low")), erster(w.get("nozzle_temperature_range_high"))
            betten = [x for x in (erster(w.get("hot_plate_temp")), erster(w.get("textured_plate_temp"))) if isinstance(x, float) and x > 0]
            flow = erster(w.get("filament_flow_ratio"))
            pa_an = erster(w.get("enable_pressure_advance"))
            k = erster(w.get("pressure_advance")) if pa_an not in (0.0, "0", None) else None
            mvs = erster(w.get("filament_max_volumetric_speed"))
            werte = [d1, d2, min(betten) if betten else None, max(betten) if betten else None, flow, k, mvs]
            werte = [round(x, 3) if isinstance(x, float) else None for x in werte]
            if not any(v is not None for v in werte):
                continue
            key = (marke, material, kurzname(name))
            v = vorzug(name)
            if key not in beste or v < beste[key][0]:
                beste[key] = (v, werte)
    profile = sorted([[m, t, n, *w] for (m, t, n), (_, w) in beste.items()])
    # Standardwerte je Material: Median über alle Profile (ohne Ausreißer durch Median)
    material = {}
    for t in sorted({p[1] for p in profile}):
        reihen = [p[3:] for p in profile if p[1] == t]
        mitte = []
        for i in range(7):
            xs = [r[i] for r in reihen if r[i] is not None and r[i] > 0]
            mitte.append(round(statistics.median(xs), 3) if xs else None)
        material[t] = mitte
    json.dump({"stand": datetime.date.today().isoformat(), "quelle": "OrcaSlicer-Filamentprofile (AGPL-3.0)",
               "profile": profile, "material": material}, open(aus, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    print(f"{len(profile)} Profile, {len(material)} Materialien → {aus}")


if __name__ == "__main__":
    main()
