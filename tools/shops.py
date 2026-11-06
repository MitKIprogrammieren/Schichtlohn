#!/usr/bin/env python3
"""Rohdaten der Herstellershops (tools/shops_roh.py) → einheitliche Zeilen wie tools/haendler/3djake.jsonl.

Zeile: shop, marke, titel, material, farbe, gewicht_g, ausfuehrung (spule/refill), preis_eur, normalpreis_eur, url, ean, artnr
Aufruf: shops.py <rohordner> <zielordner>   → <ziel>/<shop>.jsonl
"""
import html
import json
import os
import re
import sys

MATERIALIEN = ["PLA+", "PLA", "PETG", "PCTG", "PET", "ABS", "ASA", "TPU", "TPE", "PA12", "PA6", "PA", "PC", "PP", "PVA", "HIPS", "PVB", "PPS", "PEEK", "PEI", "PPA", "NYLON", "CPE", "PHA", "PMMA", "POM", "PVC", "HDPE", "PEKK", "PVDF"]
EAN = re.compile(r"^\d{13}$")


def ean_ok(k):
    if not EAN.match(k or ""):
        return False
    t = sum(int(k[j]) * (3 if j % 2 else 1) for j in range(12))
    return (10 - t % 10) % 10 == int(k[12])


def gewicht(*texte):
    for t in texte:
        t = str(t or "").lower().replace(",", ".")
        # Mehrfachpackungen: „1KG / 3 Rolls“, „5 x 1 kg“, „2er-Pack“ → Gesamtgewicht
        n = 1
        mn = re.search(r"\b([2-9]|10)\s*(?:rolls?|rollen|spools?|spulen|packs?|er[- ]?pack|stück)\b", t) or re.search(r"\b([2-9]|10)\s*[x×]\s*\d", t)
        if mn:
            n = int(mn.group(1))
        m = re.search(r"(\d+(?:\.\d+)?)\s*kg\b", t)
        mx = re.search(r"kg\s*[x×]\s*(\d{1,3})\b", t)  # Anycubic: „1 kg × 50“
        if m and mx and n == 1:
            n = int(mx.group(1))
        if m:
            return int(round(float(m.group(1)) * 1000)) * n
        m = re.search(r"(\d{2,4})\s*g\b", t)
        if m:
            return int(m.group(1))
    return None


def material(t):
    u = " " + re.sub(r"[^A-Z0-9+]+", " ", str(t).upper()) + " "
    if re.search(r" PC ?ABS ", u):  # PC-ABS ist ein eigenes Material, weder PC noch ABS
        return "PCABS"
    for m in MATERIALIEN:
        if f" {m} " in u or f" {m}-" in u or re.search(rf"\b{re.escape(m)}(?=[- ]?(CF|GF|HF|ECO|X|PRO|MATTE?|SILK))", u):
            return "PA" if m == "NYLON" else m
    return ""


def ist_filament(titel, typ=""):
    t = (titel + " " + typ).lower()
    if any(w in t for w in ("protection", "versicherung", "adapter", "platine", "düse", "nozzle", "druckplatte", "bauplatte", "swatch",
                            "farbplättchen", "gutschein", "gift card", "dryer", "trockner", "bundle", "combo", "box", "set ", "duo", "trio",
                            "plate", "platte", "sheet", "filament hub", "schneider", "cutter", "leerrolle", "masterspool",
                            "beutel", "bags", "klebestift", "sensor", "schläuche", "schlauch")):
        return False
    if re.search(r"\+\s*\d+\s*kg\b", t):  # Drucker mit Filament-Beigabe („Centauri 2 + 4 kg PLA“)
        return False
    if ("resin" in t or "harz" in t) and "filament" not in t:  # Harz für SLA-Drucker („ABS-Like Resin“)
        return False
    return bool(material(titel)) or "filament" in t


def farbe_aus_titel(titel):
    """Farbe aus einem Titel wie „PETG Filament – 1,75 mm – Burnt Copper – 1 kg Refill“ oder „PLA Hellrosa“."""
    t = html.unescape(titel)
    teile = [x.strip() for x in re.split(r"\s+[–|-]\s+|,(?!\d)", t) if x.strip()]
    for x in teile[1:]:
        if not re.search(r"\d\s*(mm|kg|g)\b|^filament$|refill", x, re.I):
            return x
    m = material(t)
    if m:
        return re.sub(rf"^.*?\b{re.escape(m)}\b[-\w+]*\s*", "", t, flags=re.I).split("–")[0].strip()
    return ""


def farbe_putzen(f):
    f = str(f or "").split("|")[-1]
    f = re.sub(r"^\s*(" + "|".join(re.escape(m) for m in MATERIALIEN) + r")(\s*[\d.]+)?\b\s*", "", f, flags=re.I)
    f = re.sub(r"\b\d+(?:[.,]\d+)?\s*(kg|g|mm)\b", "", str(f or ""), flags=re.I)
    f = re.sub(r"\b(refill|filament|spule|spool|1\.75|ship to europe)\b", "", f, flags=re.I)
    return re.sub(r"\s+", " ", f).strip(" -/–,")


def zeile(shop, marke, titel, farbe, gw, refill, preis, normal, url, ean="", artnr=""):
    titel = html.unescape(re.sub(r"\s+", " ", titel)).strip()
    farbe = farbe_putzen(farbe) or farbe_putzen(farbe_aus_titel(titel))
    return {"shop": shop, "marke": marke, "titel": titel, "material": material(titel), "farbe": html.unescape(farbe or "").strip(),
            "gewicht_g": gw or 1000, "ausfuehrung": "refill" if refill else "spule", "preis_eur": preis,
            "normalpreis_eur": normal if normal and normal > (preis or 0) else preis, "url": url, "ean": ean if ean_ok(ean) else "", "artnr": artnr}


def shopify(shop, cfg, daten):
    basis = cfg["basis"].rstrip("/")
    out = []
    for p in daten:
        titel = p.get("title") or ""
        if not ist_filament(titel, p.get("product_type") or ""):
            continue
        opts = [o.get("name", "").lower() for o in p.get("options") or []]
        for v in p.get("variants") or []:
            vt = v.get("title") or ""
            if re.search(r"resin|harz", vt, re.I):
                continue
            if v.get("available") is False:  # ausverkauft
                continue
            werte = [v.get("option1"), v.get("option2"), v.get("option3")]
            if shop == "sunlu":  # nur Ware aus dem EU-Lager
                if "europe" not in vt.lower() and "-eu-" not in (v.get("sku") or "").lower():
                    continue
            farbe = ""
            for n, w in zip(opts, werte):
                if w and any(k in n for k in ("farbe", "color", "colour")):
                    farbe = w
            if not farbe and "," in titel:  # Tinmorry: „…, 1 KG, Matte Skin“
                farbe = titel.rsplit(",", 1)[1].strip()
            if not farbe and vt != "Default Title" and len(werte) and werte[0] and not gewicht(werte[0]) and not re.search(r"mm|ship", werte[0], re.I):
                farbe = werte[0]
            marke = cfg.get("marke") or ""
            if not marke:  # Händler mit mehreren Marken (Princore): Marke aus dem Titel
                marke = titel.split()[0].strip("[]").replace("™", "").replace("®", "")
                marke = marke if marke.isupper() is False else marke.title()
            gw = gewicht(*[w for w in werte if w], vt, titel)
            preis = float(v.get("price") or 0) or None
            normal = float(v.get("compare_at_price") or 0) or None
            sku = v.get("sku") or ""
            refill = "refill" in (titel + " " + vt).lower()
            if re.search(r"2[.,]85\s*mm", vt) or (gw and gw < 200) or re.search(r"\bbundle\b|\d\s*x\s*\d", vt, re.I):
                continue
            out.append(zeile(shop, marke, titel + ("" if vt == "Default Title" else " – " + vt), farbe, gw, refill, preis, normal,
                             f"{basis}/products/{p.get('handle')}?variant={v.get('id')}", sku if ean_ok(sku) else "", "" if ean_ok(sku) else sku))
    return out


def woo(shop, cfg, daten):
    out = []
    eltern = {p["id"]: p for p in daten if p.get("type") != "variation"}
    for p in daten:
        if p.get("type") == "variable":
            continue
        name = p.get("name") or ""
        if not ist_filament(name):
            continue
        pr = p.get("prices") or {}
        kurs = 1.0
        if pr.get("currency_code") != "EUR":  # z. B. PLN bei polnischen Shops: fester Kurs aus shops.json, sonst weglassen
            kurs = (cfg.get("kurs") or {}).get(pr.get("currency_code"))
            if not kurs:
                continue
        if p.get("is_in_stock") is False or p.get("is_purchasable") is False:  # ausverkauft
            continue
        teil = 10 ** int(pr.get("currency_minor_unit") or 2)
        preis = round(int(pr.get("price") or 0) / teil / kurs, 2) or None
        normal = round(int(pr.get("regular_price") or 0) / teil / kurs, 2) or None
        va = p.get("variation")
        if isinstance(va, list):
            attr = " ".join(f"{a.get('attribute')}: {a.get('value')}" for a in va if isinstance(a, dict))
        else:
            attr = str(va or "")
        farbe = ""
        m = re.search(r"(?:Farbe|Colou?r)[^:]*:\s*([^,]+)", attr)
        if m:
            farbe = m.group(1)
        if not farbe:  # Filamentworld: „… – PLA Filament – Turkey Egg – 1.75 mm …“
            m = re.search(r"Filament\s+–\s+([^–]+?)\s+–", html.unescape(name))
            if m:
                farbe = m.group(1)
        if not farbe:  # CR3D: „PLA Hellrosa“ → Farbe = alles nach dem Material
            m = material(name)
            rest = re.sub(rf"^.*?\b{re.escape(m)}\b[-\w]*\s*", "", html.unescape(name), flags=re.I) if m else ""
            farbe = rest.split("–")[0].strip()
        gw = gewicht(attr, name)
        if re.search(r"2[.,]85\s*mm", attr + name) or (gw and gw < 200):
            continue
        marke = cfg["marke"] or re.split(r"\s+(?:&#8211;|–|-)\s+", html.unescape(name))[0].split()[0]  # Filamentworld: „Fillamentum – Extrafill – PLA …“
        out.append(zeile(shop, marke, name + (" – " + attr if attr else ""), farbe, gw, "refill" in (name + attr).lower(),
                         preis, normal, p.get("permalink") or "", "", p.get("sku") or ""))
    return out


def wix(shop, cfg, daten):
    out = []
    for p in daten:
        t = (p.get("meta") or {}).get("og:title") or p.get("titel") or ""
        t = t.split("|")[0].strip()
        preis = (p.get("meta") or {}).get("product:price:amount")
        if not t or not preis or not ist_filament(t):
            continue
        m = material(t)
        farbe = re.sub(rf"^.*?\b{re.escape(m)}\w*\s+", "", t, flags=re.I) if m else ""
        farbe = re.sub(r"\s*filament.*$", "", farbe, flags=re.I).strip()
        out.append(zeile(shop, cfg["marke"], t, farbe, gewicht(t), "refill" in t.lower(), float(preis), None, p["url"]))
    return out


def _gw(t):
    """„1.000 g“ → „1000 g“, damit gewicht() die Tausenderpunkte nicht falsch liest."""
    return re.sub(r"(\d)\.(\d{3})\b", r"\1\2", str(t or ""))


def plenty(shop, cfg, daten):
    """3D Prima: je Ausführung Name, Hersteller, Farbe, Gewicht, Preis (deutsch), EAN."""
    out = []
    for p in daten:
        if p.get("fehler") or not p.get("preis") or (p.get("waehrung") or "EUR") != "EUR" or p.get("verkaufbar") is False:
            continue
        name, var = p.get("name") or "", p.get("variante") or ""
        if not ist_filament(name):
            continue
        if re.search(r"2[.,]85|3[.,]0?\s*mm|\b3\s*mm", (p.get("dicke") or "") + " " + var):
            continue
        gw = gewicht(_gw(p.get("gewicht")), _gw(var), _gw(name))
        if gw and gw < 200:
            continue
        marke = p.get("marke") or name.split()[0]
        titel = name + (" – " + p["farbe"] if p.get("farbe") else "")
        out.append(zeile(shop, marke, titel, p.get("farbe") or "", gw, "refill" in (name + " " + var).lower(),
                         float(p["preis"]), float(p["normal"]) if p.get("normal") else None, p.get("url") or "", p.get("ean") or "", str(p.get("id") or "")))
    return out


def jtl(shop, cfg, daten):
    """iGo3D: ein Produkt mit allen Farben zum selben Preis → eine Zeile je Farbe."""
    out = []
    for p in daten:
        if p.get("fehler") or not p.get("preis") or (p.get("waehrung") or "EUR") != "EUR":
            continue
        name = p.get("name") or ""
        if not ist_filament(name) or re.search(r"2[.,]85\s*mm|\b3[.,]00?\s*mm", name):
            continue
        gw = gewicht(_gw(name))
        if gw and gw < 200:
            continue
        marke = p.get("marke") or ""
        if not marke:  # Händler mit vielen Marken: Marke = Titelanfang bis zum Material
            m = material(name)
            marke = re.split(rf"\s+{re.escape(m)}\b", name, maxsplit=1, flags=re.I)[0].strip() if m else name.split()[0]
        refill = bool(re.search(r"refill|ohne spule", name, re.I))
        farben = p.get("farben") or [""]
        for f in farben:
            out.append(zeile(shop, marke, name + (" – " + f if f else ""), f, gw, refill, float(p["preis"]),
                             float(p["normal"]) if p.get("normal") else None, p["url"], p.get("ean") if len(farben) == 1 else ""))
    return out


def seiten(shop, cfg, daten):
    """Produktseiten (ld+json): Preis in EUR, andere Währungen über den festen Kurs aus shops.json (z. B. DKK)."""
    out = []
    kurse = cfg.get("kurs") or {}
    for p in daten:
        if p.get("fehler") or not p.get("preis") or re.search(r"OutOfStock|SoldOut|Discontinued", str(p.get("verfuegbar") or "")):
            continue
        cur = p.get("waehrung") or "EUR"
        if cur != "EUR":
            if cur not in kurse:
                continue
            p["preis"] = round(p["preis"] / kurse[cur], 2)
        name = p.get("name") or ""
        if re.search(r"\d+\s*x\s+\w+\s+\d+\s*x", name, re.I):  # Mischpakete „5x hvid 5x sort“
            continue
        if not ist_filament(name) or re.search(r"2[.,]85|\b3[.,]00?\s*mm", name + " " + p["url"]):
            continue
        gw = gewicht(_gw(name))
        if not gw:  # colorFabb: „PLA/PHA STANDARDSCHWARZ 1.75 / 750“ bzw. …-1-75-750
            m = re.search(r"/\s*(\d{3,4})\s*$", name) or re.search(r"-1-75-(\d{3,4})\b", p["url"])
            gw = int(m.group(1)) if m else None
        if gw and gw < 200:
            continue
        farbe = p.get("farbe") or ""
        if not farbe and cfg.get("farbe_nach_material"):
            m = material(name)
            farbe = re.sub(r"\s*\d[.,]\d+\s*(/\s*\d+)?\s*$", "", re.sub(rf"^.*?\b{re.escape(m)}\b(/[A-Z]+)?\s*", "", name, flags=re.I)).strip().title() if m else ""
        marke = cfg.get("marke") or p.get("marke") or ""
        if not marke:
            m = material(name)
            marke = re.split(rf"\s+{re.escape(m)}\b", name, maxsplit=1, flags=re.I)[0].strip() if m else name.split()[0]
        out.append(zeile(shop, marke, name, farbe, gw, bool(re.search(r"refill|ohne spule", name, re.I)), round(p["preis"], 2), None,
                         p["url"], p.get("ean") or "", p.get("sku") or ""))
    return out


DA_FARBEN = {"sort": "Schwarz", "hvid": "Weiß", "rød": "Rot", "blå": "Blau", "grøn": "Grün", "gul": "Gelb", "grå": "Grau", "lilla": "Lila",
             "brun": "Braun", "sølv": "Silber", "guld": "Gold", "lyserød": "Rosa", "mørkegrå": "Dunkelgrau", "lysegrå": "Hellgrau",
             "mørkeblå": "Dunkelblau", "lyseblå": "Hellblau", "mørkegrøn": "Dunkelgrün", "lysegrøn": "Hellgrün", "klar": "Transparent", "natur": "Natur"}


PL_FARBEN = {"czarny": "Schwarz", "czarna": "Schwarz", "biały": "Weiß", "biala": "Weiß", "biały": "Weiß", "szary": "Grau", "czerwony": "Rot",
             "niebieski": "Blau", "zielony": "Grün", "żółty": "Gelb", "zolty": "Gelb", "pomarańczowy": "Orange", "fioletowy": "Lila",
             "różowy": "Rosa", "brązowy": "Braun", "srebrny": "Silber", "złoty": "Gold", "naturalny": "Natur", "transparentny": "Transparent",
             "beżowy": "Beige", "granatowy": "Dunkelblau", "turkusowy": "Türkis", "grafitowy": "Graphit", "ciemnoszary": "Dunkelgrau",
             "jasnoszary": "Hellgrau", "ciemnozielony": "Dunkelgrün", "jasnoniebieski": "Hellblau", "miedziany": "Kupfer", "oliwkowy": "Oliv"}


def pl_farbe(f):
    return " ".join(PL_FARBEN.get(w.lower(), w) for w in str(f or "").split())


def da_farbe(f):
    return " ".join(DA_FARBEN.get(w.lower(), w) for w in str(f or "").split())


_MARKE_MUELL = re.compile(r"\s+(?:" + "|".join(re.escape(m) for m in MATERIALIEN) + r"|PC[-/ ]?ABS|FILAMENT|SUPPORT|VALUE PACK|HIGH PERFORMANCE)\b.*$", re.I)


def marken_vereinheitlichen(zeilen, fest=()):
    """Gleiche Marke, eine Schreibweise: „ELEGOO“/„Elegoo“ zusammen, „Polymaker PolyMax Tough“ → „Polymaker“,
    „Elegoo PLA+ Filament“ → „Elegoo“ (Händler wie iGo3D liefern nur den Titelanfang)."""
    import collections
    k = lambda m: re.sub(r"[^a-z0-9]", "", str(m).lower())
    n = collections.Counter(z["marke"] for z in zeilen if z.get("marke"))
    sauber = {}
    fest_k = {k(m) for m in fest}
    for m in fest:  # Marken der Herstellershops sind immer richtig geschrieben („Das Filament“)
        sauber[k(m)] = m
    for m, c in n.most_common():
        if k(m) in fest_k:
            continue
        if len(m.split()) <= 2 and not _MARKE_MUELL.search(" " + m):
            best = sauber.get(k(m))
            if not best or (best.isupper() and not m.isupper()):
                sauber[k(m)] = m
    # Gleiches erstes Wort = eine Marke („Polymaker PolyMax“ → „Polymaker“, „Bambu“ → „Bambu Lab“, „Makerbot Method“ → „Makerbot“)
    gruppen = collections.defaultdict(list)
    for kk, m in sauber.items():
        gruppen[k(m.split()[0])].append(m)
    for g in gruppen.values():
        if len(g) < 2:
            continue
        f = [m for m in g if k(m) in fest_k]
        if f:  # Herstellershop gibt die Schreibweise vor
            if len(f) == 1 and len(f[0].split()) == 1:
                for m in g:
                    sauber[k(m)] = f[0]
            continue
        zahl = lambda m: sum(c for x, c in n.items() if k(x) == k(m))
        haupt = max(g, key=zahl)
        zwei = {k(m) for m in g if len(m.split()) == 2}
        if len(zwei) > 1:  # mehrere Produktlinien → nur das erste Wort
            einzel = [m for m in g if len(m.split()) == 1]
            haupt = einzel[0] if einzel else haupt.split()[0]
        for m in g:
            sauber[k(m)] = haupt
    namen = sorted(set(sauber.values()), key=lambda m: -len(m))
    def kanon(m):
        m0 = re.sub(r"^original\s+", "", str(m).strip(), flags=re.I)
        if k(m0) in sauber:
            return sauber[k(m0)]
        for c in namen:
            if m0.lower().startswith(c.lower() + " "):
                return c
        kurz = _MARKE_MUELL.sub("", m0).strip()
        return sauber.get(k(kurz), kurz or m)
    for z in zeilen:
        if z.get("marke"):
            z["marke"] = kanon(z["marke"])
    return zeilen


def alle(roh, shops):
    zeilen = []
    for k, cfg in shops.items():
        pfad = os.path.join(roh, k + ".json")
        if not os.path.exists(pfad):
            continue
        daten = json.load(open(pfad, encoding="utf-8"))
        f = {"shopify": shopify, "woo": woo, "wix": wix, "plenty": plenty, "jtl": jtl, "seiten": seiten}[cfg["art"]]
        z = f(k, cfg, daten)
        if cfg.get("nur_mit_material"):  # Hersteller- und Händlershops mit viel Zubehör: nur eindeutige Filamente
            z = [x for x in z if x["material"]]
        if cfg.get("sprache") == "da":
            for x in z:
                x["farbe"] = da_farbe(x["farbe"])
        for x in z:  # Reste wie „( / )“ aus Variantennamen entfernen
            x["farbe"] = re.sub(r"\(\s*[/,\s]*\)", "", x["farbe"] or "").strip(" -–")
        if cfg.get("farbe_nach_strich"):  # Eryone: „Lite Matte - Black“ → „Black“
            for x in z:
                if " - " in x["farbe"]:
                    x["farbe"] = x["farbe"].rsplit(" - ", 1)[1].strip()
        if cfg.get("farbe_in_anfuehrung"):  # Fillamentum: PLA Extrafill „Marrakesh Red“ → „Marrakesh Red“
            for x in z:
                m = re.search(r'["“„]([^"“”„]+)["”“]', x["titel"])
                if m:
                    x["farbe"] = m.group(1).strip()
        if cfg.get("sprache") == "pl":
            for x in z:
                x["farbe"] = pl_farbe(x["farbe"])
        for x in z:
            x["shopname"] = cfg["name"]
        zeilen += z
    return marken_vereinheitlichen(zeilen, [c["marke"] for c in shops.values() if c.get("marke")] + ["3DJAKE"])


def main():
    shops = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "shops.json"), encoding="utf-8"))
    roh, ziel = sys.argv[1], sys.argv[2]
    os.makedirs(ziel, exist_ok=True)
    z = alle(roh, shops)
    for k in shops:
        mit = [x for x in z if x["shop"] == k]
        with open(os.path.join(ziel, k + ".jsonl"), "w", encoding="utf-8") as f:
            for x in mit:
                f.write(json.dumps(x, ensure_ascii=False) + "\n")
        print(k, len(mit))


if __name__ == "__main__":
    main()
