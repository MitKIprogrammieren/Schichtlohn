#!/usr/bin/env python3
"""Baut filamentdb.json für den Scanner im Lager.

Quellen (beide MIT-Lizenz):
  Open Filament Database  https://github.com/OpenFilamentCollective/open-filament-database
  SpoolmanDB              https://github.com/Donkie/SpoolmanDB

Aufruf:  python3 tools/filamentdb.py <pfad-ofd-repo> <pfad-spoolmandb-repo> [ausgabe.json]

Ausgabe (kompakt, damit sie schnell lädt):
  b  Marken
  l  Linien  [marke, material, name, dichte, düse_min, düse_max, bett_min, bett_max]
  c  Farben  [linie, farbname, hex, gewicht, durchmesser, leerspule, refill(0/1), besonderheiten, quelle(0=OFD,1=SpoolmanDB)]
  g  Barcodes  {ziffern ohne führende Nullen: [farbe, gewicht, refill]}
"""
import datetime
import glob
import json
import os
import re
import sys

TRAITS = {
    "matte": "Matt", "silk": "Seide", "high_flow": "HF", "translucent": "Transparent",
    "transparent": "Transparent", "contains_carbon_fiber": "CF", "contains_glass_fiber": "GF",
    "glitter": "Glitzer", "glow": "Leuchtend", "imitates_marble": "Marmor", "imitates_metal": "Metallic",
    "contains_wood": "Holz", "imitates_wood": "Holz",
}
WORDS = {
    "basic": "Basic", "matte": "Matt", "matt": "Matt", "silk": "Seide", "glow": "Leuchtend",
    "sparkle": "Glitzer", "glitter": "Glitzer", "galaxy": "Glitzer", "metal": "Metallic",
    "metallic": "Metallic", "marble": "Marmor", "wood": "Holz", "translucent": "Transparent",
    "transparent": "Transparent", "cf": "CF", "gf": "GF", "hf": "HF",
}
ORDER = ["Basic", "Matt", "Seide", "Glänzend", "Glitzer", "Metallic", "Transparent", "Marmor", "Holz", "Leuchtend", "GF", "CF", "HF"]


def load(p):
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def norm(s):
    return re.sub(r"[^a-z0-9]", "", str(s or "").lower())


def code_key(s):
    d = re.sub(r"\D", "", str(s or "")).lstrip("0")
    return d if len(d) >= 6 else ""


def num(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return int(v) if v == int(v) else v


def hexval(h):
    if isinstance(h, list):
        h = h[0] if h else ""
    h = str(h or "").strip().lstrip("#")
    return "#" + h[:6].lower() if re.fullmatch(r"[0-9a-fA-F]{6}([0-9a-fA-F]{2})?", h) else "#888888"


def bes_of(line, material, extra=()):
    out = set(extra)
    mat = norm(material)
    for w in re.split(r"[\s\-_/+]+", str(line or "").lower()):
        if w in WORDS and w != mat and w not in mat:
            out.add(WORDS[w])
    return ",".join(b for b in ORDER if b in out)


class DB:
    def __init__(self):
        self.b, self.bi = [], {}
        self.l, self.li = [], {}
        self.c, self.ci = [], {}
        self.g = {}

    def brand(self, name):
        k = norm(name)
        if k not in self.bi:
            self.bi[k] = len(self.b)
            self.b.append(name)
        return self.bi[k]

    def line(self, b, material, name, dens, d1, d2, b1, b2):
        k = (b, norm(material), norm(name))
        if k not in self.li:
            self.li[k] = len(self.l)
            self.l.append([b, material, name, num(dens), num(d1), num(d2), num(b1), num(b2)])
        return self.li[k]

    def color(self, l, name, hx, w, dia, spool, refill, bes, src):
        k = (l, norm(name))
        if k in self.ci:
            return self.ci[k], False
        self.ci[k] = len(self.c)
        self.c.append([l, name, hx, num(w), num(dia), num(spool), 1 if refill else 0, bes, src])
        return self.ci[k], True


def pick_size(sizes):
    """Bevorzugt 1 kg mit 1,75 mm, sonst die erste Größe."""
    for z in sizes:
        if z.get("filament_weight") == 1000 and z.get("diameter") == 1.75 and not z.get("spool_refill"):
            return z
    return sizes[0] if sizes else {}


def add_ofd(db, root):
    data = os.path.join(root, "data")
    for bdir in sorted(glob.glob(os.path.join(data, "*", ""))):
        bj = os.path.join(bdir, "brand.json")
        if not os.path.exists(bj):
            continue
        brand = load(bj).get("name") or os.path.basename(bdir.rstrip("/"))
        bi = db.brand(brand)
        for fj in sorted(glob.glob(os.path.join(bdir, "*", "*", "filament.json"))):
            fdir = os.path.dirname(fj)
            material = os.path.basename(os.path.dirname(fdir))
            mj = os.path.join(os.path.dirname(fdir), "material.json")
            if os.path.exists(mj):
                material = load(mj).get("material") or material
            f = load(fj)
            if f.get("discontinued"):
                continue
            li = db.line(bi, material, f.get("name") or "", f.get("density"),
                         f.get("min_print_temperature"), f.get("max_print_temperature"),
                         f.get("min_bed_temperature"), f.get("max_bed_temperature"))
            lbes = bes_of(f.get("name"), material)
            for vj in sorted(glob.glob(os.path.join(fdir, "*", "variant.json"))):
                v = load(vj)
                if v.get("discontinued"):
                    continue
                sj = os.path.join(os.path.dirname(vj), "sizes.json")
                sizes = [z for z in (load(sj) if os.path.exists(sj) else []) if not z.get("discontinued")] or (load(sj) if os.path.exists(sj) else [])
                z = pick_size(sizes)
                tr = v.get("traits") or {}
                tr = [k for k, on in tr.items() if on] if isinstance(tr, dict) else list(tr)
                bes = bes_of(f.get("name"), material, [TRAITS[t] for t in tr if t in TRAITS] + ([x for x in lbes.split(",") if x]))
                ci, _ = db.color(li, v.get("name") or "", hexval(v.get("color_hex")), z.get("filament_weight"),
                                 z.get("diameter"), z.get("empty_spool_weight"), z.get("spool_refill"), bes, 0)
                for s in sizes:
                    for key in ("gtin", "ean"):
                        k = code_key(s.get(key))
                        if k and k not in db.g:
                            db.g[k] = [ci, num(s.get("filament_weight")), 1 if s.get("spool_refill") else 0]


def add_sdb(db, root):
    for p in sorted(glob.glob(os.path.join(root, "filaments", "*.json"))):
        d = load(p)
        bi = db.brand(d.get("manufacturer") or os.path.splitext(os.path.basename(p))[0])
        for f in d.get("filaments", []):
            material = f.get("material") or ""
            name = re.sub(r"\s+", " ", (f.get("name") or "").replace("{color_name}", "")).strip(" -")
            if not name:
                name = material
            ws = f.get("weights") or [{}]
            w = next((x for x in ws if x.get("weight") == 1000), ws[0])
            dias = f.get("diameters") or [1.75]
            dia = 1.75 if 1.75 in dias else dias[0]
            et, bt = f.get("extruder_temp"), f.get("bed_temp")
            li = db.line(bi, material, name, f.get("density"), et, et, bt, bt)
            extra = []
            if f.get("finish") == "matte":
                extra.append("Matt")
            if f.get("translucent"):
                extra.append("Transparent")
            if f.get("glow"):
                extra.append("Leuchtend")
            bes = bes_of(name, material, extra)
            for c in f.get("colors", []):
                hx = c.get("hex") or (c.get("hexes") or [""])[0]
                db.color(li, c.get("name") or "", hexval(hx), w.get("weight"), dia, w.get("spool_weight"),
                         w.get("spool_type") == "refill", bes, 1)


def main():
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    ofd, sdb = sys.argv[1], sys.argv[2]
    out = sys.argv[3] if len(sys.argv) > 3 else os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "filamentdb.json")
    db = DB()
    add_ofd(db, ofd)  # OFD zuerst: hat Vorrang bei gleichen Sorten
    add_sdb(db, sdb)
    res = {
        "v": 1,
        "stand": datetime.date.today().isoformat(),
        "quellen": ["Open Filament Database (MIT)", "SpoolmanDB (MIT)"],
        "b": db.b, "l": db.l, "c": db.c, "g": db.g,
    }
    with open(out, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, separators=(",", ":"))
    print(f"{len(db.b)} Marken, {len(db.l)} Linien, {len(db.c)} Farben, {len(db.g)} Barcodes → {os.path.normpath(out)} ({os.path.getsize(out) // 1024} KB)")


if __name__ == "__main__":
    main()
