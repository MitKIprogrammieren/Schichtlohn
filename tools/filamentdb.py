#!/usr/bin/env python3
"""Baut filamentdb.json für den Scanner im Lager.

Quellen (beide MIT-Lizenz):
  Open Filament Database  https://github.com/OpenFilamentCollective/open-filament-database
  SpoolmanDB              https://github.com/Donkie/SpoolmanDB

Aufruf:  python3 tools/filamentdb.py <pfad-ofd-repo> <pfad-spoolmandb-repo> [ausgabe.json]

Ausgabe (kompakt, damit sie schnell lädt):
  b  Marken
  l  Linien  [marke, material, name, dichte, düse_min, düse_max, bett_min, bett_max, suchwörter]
     suchwörter: Mutter-Marke und frühere Namen, z. B. „Polymaker PolyTerra“ bei Panchroma Matte
  c  Farben  [linie, farbname, hex, gewicht, durchmesser, leerspule, refill(0/1), besonderheiten, quelle(0=OFD,1=SpoolmanDB)]
  g  Barcodes  {ziffern ohne führende Nullen: [farbe, gewicht, refill]}
  h  Händler   [name]            hu  Basisadresse je Händler
  o  Angebote  {farbe: [[händler, preis_eur, pfad, artikelnr, normalpreis_eur, refill(0/1), gewicht_g], …]}
  t  Hinweise  {linie: [trocknen_c, trocknen_h, düsenhinweis]}

Zusätzlich eingemischt (beide optional, eine JSON-Zeile je Farbe):
  tools/haendler/<händler>.jsonl   Shopdaten (EAN, Preis, Link, Artikelnr., Druckwerte)
  tools/ergaenzungen.json          eigene Sorten, die in OFD und SpoolmanDB fehlen (Liste)
  quelle in c: 0=OFD, 1=SpoolmanDB, 2=Händler/Ergänzung
"""
import difflib
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


def words(s):
    return [w for w in re.split(r"[^a-z0-9]+", str(s or "").lower()) if w]


GENERIC = {"pla", "petg", "abs", "asa", "tpu", "filament", "basic", "formerly", "the", "and", "3d", "plus"}


def norm(s):
    return re.sub(r"[^a-z0-9]", "", str(s or "").lower())


def code_key(s):
    d = re.sub(r"\D", "", str(s or "")).lstrip("0")
    return d if len(d) >= 6 else ""


def ean_ok(s):
    d = re.sub(r"\D", "", str(s or ""))
    if len(d) not in (8, 12, 13, 14):
        return False
    body, chk = d[:-1], int(d[-1])
    tot = sum(int(c) * (3 if i % 2 == 0 else 1) for i, c in enumerate(reversed(body)))
    return (10 - tot % 10) % 10 == chk


def mat_ok(mat, line_mat, line_name):
    """Gleiches Material – auch „PETG-CF“ (SpoolmanDB) gegen PETG mit Serie „PETG-CF“ (OFD)."""
    a, b = norm(mat), norm(line_mat)
    if a == b:
        return True
    if a.startswith(b) and len(a) > len(b):
        rest = a[len(b):]
        return rest in norm(line_name) or rest in set(words(line_name))
    return False


def cnorm(s):
    """Farbnamen vergleichbar machen: colour/color, grey/gray, Leerzeichen und Zeichen egal."""
    s = str(s or "").lower().replace("colour", "color").replace("grey", "gray")
    return norm(s)


def typo(a, b):
    """Gleiche Farbe mit Tippfehler: gleiche Wortzahl, genau ein Wort leicht verschieden, keine Ziffern."""
    wa, wb = words(str(a).replace("grey", "gray")), words(str(b).replace("grey", "gray"))
    if len(wa) != len(wb):
        return 0
    d = [(x, y) for x, y in zip(wa, wb) if x != y]
    if len(d) != 1:
        return 0
    x, y = d[0]
    if not (x.isalpha() and y.isalpha() and min(len(x), len(y)) >= 4):
        return 0
    r = difflib.SequenceMatcher(None, x, y).ratio()
    return r if r >= 0.75 else 0


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
        self.ofd_lines = set()
        self.h, self.hu = [], []
        self.o = {}
        self.t = {}

    def ofd_partner(self, brand, material, name, lines=None):
        """OFD-Linie, die dieselbe Sorte meint (z. B. SpoolmanDB „Panchroma Matte (Formerly PolyTerra)“ bei Polymaker)."""
        sw = set(words(brand)) | set(words(name))
        mat = norm(material)
        best = None
        for li in (self.ofd_lines if lines is None else lines):
            l = self.l[li]
            if not mat_ok(material, l[1], l[2]):
                continue
            bw = [w for w in words(self.b[l[0]]) if w not in GENERIC]
            pw = [w for w in words(l[8]) if w not in GENERIC]
            if not (bw and all(w in sw for w in bw)) and not (pw and all(w in sw for w in pw)):
                continue
            lw = [w for w in words(l[2]) if w not in GENERIC and w not in bw and w != mat]
            if not lw or not all(w in sw for w in lw):
                continue
            if best is None or len(lw) > best[0]:
                best = (len(lw), li)
        return best[1] if best else None

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
            self.l.append([b, material, name, num(dens), num(d1), num(d2), num(b1), num(b2), ""])
        return self.li[k]

    def alias(self, l, text):
        have = set(words(self.l[l][8])) | set(words(self.b[self.l[l][0]])) | set(words(self.l[l][2]))
        neu = [w for w in dict.fromkeys(words(text)) if w not in have and w not in GENERIC and len(w) > 2]
        if neu:
            self.l[l][8] = (self.l[l][8] + " " + " ".join(neu)).strip()

    def find_color(self, l, name, hx=None):
        k = (l, norm(name))
        if k in self.ci:
            return self.ci[k]
        best = None
        for (ll, nn), ci in self.ci.items():
            if ll != l:
                continue
            r = 1.0 if cnorm(self.c[ci][1]) == cnorm(name) else (typo(self.c[ci][1], name) if hx and hx != "#888888" and self.c[ci][2] == hx else 0)
            if r:
                if best is None or r > best[0]:
                    best = (r, ci)
        return best[1] if best else None

    def color(self, l, name, hx, w, dia, spool, refill, bes, src):
        k = (l, norm(name))
        if k in self.ci:
            return self.ci[k], False
        f = self.find_color(l, name, hx)
        if f is not None:  # Tippfehler-Doppelte, z. B. „Indigue Blue“ neben „Indigo Blue“
            self.ci[k] = f
            return f, False
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
    namen = {}
    for bj in glob.glob(os.path.join(data, "*", "brand.json")):
        b = load(bj)
        namen[b.get("id") or os.path.basename(os.path.dirname(bj))] = b.get("name")
    for bdir in sorted(glob.glob(os.path.join(data, "*", ""))):
        bj = os.path.join(bdir, "brand.json")
        if not os.path.exists(bj):
            continue
        bjd = load(bj)
        brand = bjd.get("name") or os.path.basename(bdir.rstrip("/"))
        parent = namen.get(bjd.get("parent_brand") or "") or ""
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
            if parent:
                db.alias(li, parent)
            db.ofd_lines.add(li)
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
            partner = db.ofd_partner(db.b[bi], material, name)
            if partner is not None:
                db.alias(partner, db.b[bi] + " " + name)
                li = partner
            else:
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


DE_EN = {
    "schwarz": "black", "weiss": "white", "weiß": "white", "grau": "gray", "grün": "green", "gruen": "green", "rot": "red",
    "blau": "blue", "gelb": "yellow", "lila": "purple", "violett": "purple", "braun": "brown", "silber": "silver",
    "türkis": "turquoise", "natur": "natural", "anthrazit": "anthracite", "kupfer": "copper", "hell": "light",
    "dunkel": "dark", "hellblau": "light blue", "dunkelblau": "dark blue", "hellgrün": "light green",
    "dunkelgrün": "dark green", "hellgrau": "light gray", "dunkelgrau": "dark gray", "feuerrot": "fire red",
    "smaragd": "emerald", "militärgrün": "military green", "transparent": "transparent", "neon": "neon",
    "pink": "pink", "orange": "orange", "beige": "beige", "gold": "gold", "bronze": "bronze", "magenta": "magenta",
}


VORSILBEN = {"hell": "light", "dunkel": "dark", "pastell": "pastel"}

# Serien, die beim Händler unter altem Namen laufen: (marke, serie) → (marke, linie) in der Datenbank
UMBENANNT = {("polymaker", "polyterrapla"): ("panchroma", "mattepla")}


def de_wort(x):
    if x in DE_EN:
        return DE_EN[x]
    for v, e in VORSILBEN.items():  # „Pastellblau“ → „pastel blue“
        if x.startswith(v) and x[len(v):] in DE_EN:
            return e + " " + DE_EN[x[len(v):]]
    return x


def farb_varianten(name):
    """Farbname plus englische Übersetzung (3DJake nennt manche Farben deutsch)."""
    w = str(name or "").lower().split()
    en = " ".join(de_wort(x) for x in w)
    out = [name]
    if en != str(name).lower():
        out.append(en)
    if "natural" in en:
        out.append(en.replace("natural", "nature"))
    return out


def find_brand(db, marke):
    k = norm(marke)
    if k in db.bi:
        return db.bi[k]
    for bk, bi in db.bi.items():  # „eSUN“ ↔ „eSUN 3D“
        if len(k) >= 4 and (bk.startswith(k) or k.startswith(bk)) and len(bk) >= 4:
            return bi
    return db.brand(marke)


SERIEN_KW = {"silk", "tough", "matte", "translucent", "sparkle", "metal", "marble", "glow", "wood", "aero",
             "cf", "gf", "hf", "galaxy", "gradient", "pure", "fr", "dual", "multi"}


def serien_kw(text):
    out = set()
    for w in words(text):
        w = re.sub(r"\d+$", "", w)  # CF10 → cf
        w = {"matt": "matte", "silkplus": "silk"}.get(w, w)
        if w in SERIEN_KW:
            out.add(w)
    return out


KONFLIKTE = []


def brand_lines(db, bi):
    return [i for i, l in enumerate(db.l) if l[0] == bi]


def find_line(db, bi, material, serie):
    serie = serie or material
    cand = brand_lines(db, bi)
    li = db.ofd_partner(db.b[bi], material, serie, cand)
    if li is not None:
        return li
    k = (bi, norm(material), norm(serie))
    if k in db.li:
        return db.li[k]
    for i in cand:  # „PLA Matte“ ↔ Linie „Matte“ beim selben Material
        l = db.l[i]
        if mat_ok(material, l[1], l[2]) and norm(serie).replace(norm(material), "") == norm(l[2]).replace(norm(l[1]), ""):
            return i
    return None


def add_rows(db, rows, haendler=None, basis=""):
    """Shopdaten oder eigene Ergänzungen einmischen. Gibt (neu, angebote, barcodes) zurück."""
    hi = None
    if haendler:
        if haendler not in db.h:
            db.h.append(haendler)
            db.hu.append(basis)
        hi = db.h.index(haendler)
    neu = ang = bc = 0
    # Serie → Linie lernen, wo die EAN schon bekannt ist (gilt dann auch für Zeilen derselben Serie ohne EAN)
    lern = {}
    for r in rows:
        k = code_key(r.get("ean")) if ean_ok(r.get("ean")) else ""
        if k and k in db.g:
            lern.setdefault((norm(r.get("marke")), norm(r.get("serie"))), db.c[db.g[k][0]][0])
    for r in rows:
        if not r.get("marke") or not r.get("farbe"):
            continue
        dia = r.get("durchmesser") or 1.75
        if num(dia) not in (1.75, None):
            continue
        refill = 1 if r.get("ausfuehrung") == "refill" else 0
        ean = r.get("ean") if ean_ok(r.get("ean")) else None
        k = code_key(ean)
        ci = db.g[k][0] if k and k in db.g else None
        if ci is not None and r.get("serie"):
            l0 = db.l[db.c[ci][0]]
            a, b = serien_kw(r["serie"] + " " + (r.get("material") or "")), serien_kw(l0[1] + " " + l0[2])
            if a != b:  # Barcode steht in der Datenbank bei einer anderen Serie als beim Händler → Händler gilt
                KONFLIKTE.append(f"{r['marke']} {r['serie']} {r['farbe']} (EAN {r.get('ean')}): war {l0[2]} {db.c[ci][1]}")
                ci = None
        if ci is None:
            bi = find_brand(db, r["marke"])
            material = r.get("material") or "PLA"
            li = lern.get((norm(r.get("marke")), norm(r.get("serie"))))
            um = UMBENANNT.get((norm(r.get("marke")), norm(r.get("serie"))))
            if li is None and um:
                li = next((i for i, l in enumerate(db.l) if norm(db.b[l[0]]) == um[0] and norm(l[2]) == um[1]), None)
            if li is None:
                li = find_line(db, bi, material, r.get("serie"))
            if li is None:
                li = db.line(bi, material, r.get("serie") or material, r.get("dichte"),
                             r.get("duese_min"), r.get("duese_max"), r.get("bett_min"), r.get("bett_max"))
            ci = None
            for fn in farb_varianten(r["farbe"]):
                ci = db.find_color(li, fn, hexval(r.get("hex")) if r.get("hex") else None)
                if ci is not None:
                    break
            if ci is None:
                ci, _ = db.color(li, r["farbe"], hexval(r.get("hex")), r.get("gewicht_g") or 1000, dia, None, refill,
                                 bes_of(r.get("serie"), material, r.get("besonderheiten") or []), 2)
                neu += 1
        if k and (k not in db.g or db.g[k][0] != ci):
            if k not in db.g:
                bc += 1
            db.g[k] = [ci, num(r.get("gewicht_g")) or db.c[ci][3], refill]
        li = db.c[ci][0]
        l = db.l[li]
        for j, f in ((4, "duese_min"), (5, "duese_max"), (6, "bett_min"), (7, "bett_max")):
            if l[j] is None and num(r.get(f)) is not None:
                l[j] = num(r.get(f))
        tc, th, dh = num(r.get("trocknen_c")), num(r.get("trocknen_h")), (r.get("duese_hinweis") or "").strip()
        if tc or th or dh:
            alt = db.t.get(li, [None, None, ""])
            db.t[li] = [alt[0] or tc, alt[1] or th, alt[2] or dh]
        url = r.get("url") or ""
        if hi is not None and url:
            pfad = url[len(basis):] if basis and url.startswith(basis) else url
            preis = num(r.get("preis_eur"))
            liste = db.o.setdefault(ci, [])
            eintrag = [hi, preis, pfad, r.get("artnr") or "", num(r.get("normalpreis_eur")) or preis, refill, num(r.get("gewicht_g")) or db.c[ci][3]]
            if all(not (e[0] == hi and e[2] == pfad) for e in liste):
                liste.append(eintrag)
                ang += 1
    return neu, ang, bc


HAENDLER = {"3djake": ("3DJake", "https://www.3djake.de/")}


def read_jsonl(p):
    out = []
    with open(p, encoding="utf-8") as f:
        for z in f:
            z = z.strip()
            if z:
                try:
                    out.append(json.loads(z))
                except ValueError:
                    pass
    return out


def main():
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    ofd, sdb = sys.argv[1], sys.argv[2]
    out = sys.argv[3] if len(sys.argv) > 3 else os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "filamentdb.json")
    db = DB()
    add_ofd(db, ofd)  # OFD zuerst: hat Vorrang bei gleichen Sorten
    add_sdb(db, sdb)
    hier = os.path.dirname(os.path.abspath(__file__))
    quellen = ["Open Filament Database (MIT)", "SpoolmanDB (MIT)"]
    erg = os.path.join(hier, "ergaenzungen.json")
    if os.path.exists(erg):
        n, _, b = add_rows(db, load(erg))
        print(f"Ergänzungen: {n} neue Farben, {b} Barcodes")
    for p in sorted(glob.glob(os.path.join(hier, "haendler", "*.jsonl"))):
        key = os.path.splitext(os.path.basename(p))[0]
        name, basis = HAENDLER.get(key, (key, ""))
        n, a, b = add_rows(db, read_jsonl(p), name, basis)
        quellen.append(name)
        print(f"{name}: {a} Angebote, {n} neue Farben, {b} neue Barcodes, {len(KONFLIKTE)} Barcodes korrigiert")
        for x in KONFLIKTE:
            print("  korrigiert:", x)
        KONFLIKTE.clear()
    res = {
        "v": 1,
        "stand": datetime.date.today().isoformat(),
        "quellen": quellen,
        "b": db.b, "l": db.l, "c": db.c, "g": db.g,
        "h": db.h, "hu": db.hu,
        "o": {str(k): v for k, v in db.o.items()},
        "t": {str(k): v for k, v in db.t.items()},
    }
    with open(out, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, separators=(",", ":"))
    print(f"{len(db.b)} Marken, {len(db.l)} Linien, {len(db.c)} Farben, {len(db.g)} Barcodes, {sum(map(len, db.o.values()))} Angebote → {os.path.normpath(out)} ({os.path.getsize(out) // 1024} KB)")


if __name__ == "__main__":
    main()
