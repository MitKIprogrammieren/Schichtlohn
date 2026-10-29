#!/usr/bin/env python3
"""3DJake täglich auffrischen: Preise, Normalpreise und EAN der bekannten Filamentseiten neu lesen
und neue Farben derselben Marken über die Verweise auf den Seiten finden.

robots.txt von 3DJake sperrt nur /kunden/ und /webshop/ – Produktseiten sind erlaubt. Abruf mit Pause.
Aufruf: jake.py tools/haendler/3djake.jsonl [max_seiten]"""
import html
import json
import re
import sys
import time
import urllib.parse
import urllib.request

UA = "Mozilla/5.0 (compatible; SchichtLohn-Preise/1.0; +https://github.com/MitKIprogrammieren/Schichtlohn)"
BASIS = "https://www.3djake.de/"
PAUSE = 0.8


def holen(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "de-DE"})
    with urllib.request.urlopen(req, timeout=40) as r:
        return r.read().decode("utf-8", "replace")


def ean_ok(k):
    if not re.fullmatch(r"\d{13}", k or ""):
        return False
    t = sum(int(k[j]) * (3 if j % 2 else 1) for j in range(12))
    return (10 - t % 10) % 10 == int(k[12])


def zahl(t):
    t = html.unescape(t or "").replace("\xa0", " ")
    m = re.search(r"(\d{1,4}(?:\.\d{3})*,\d{2})", t)
    return float(m.group(1).replace(".", "").replace(",", ".")) if m else None


def lesen(url, h):
    """Produktseite → Felder; None, wenn kein Filament mit 1,75 mm."""
    prod = None
    for x in re.findall(r'<script type="application/ld\+json">(.*?)</script>', h, re.S):
        try:
            d = json.loads(x)
        except ValueError:
            continue
        for y in d if isinstance(d, list) else [d]:
            if isinstance(y, dict) and y.get("@type") == "Product":
                prod = y
    if not prod:
        return None
    off = prod.get("offers") or {}
    if isinstance(off, list):
        off = off[0] if off else {}
    if off.get("priceCurrency", "EUR") != "EUR":
        return None
    preis = float(off.get("price") or 0) or None
    m = re.search(r'class="p-price__instead">([^<]+)<', h) or re.search(r'original-price-formatted="([^"]+)"', h)
    normal = zahl(m.group(1)) if m else None
    text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", h))
    dm = re.search(r"Durchmesser:\s*([\d,]+)\s*mm", text)
    if dm and dm.group(1) not in ("1,75",):
        return None
    inh = re.search(r"Inhalt:\s*([\d.]+)\s*(kg|g)\b", text)
    gew = None
    if inh:
        v = float(inh.group(1).replace(".", "")) if inh.group(2) == "g" else float(inh.group(1)) * 1000
        gew = int(v)
    name = html.unescape(prod.get("name") or "")
    aus = "refill" if re.search(r"\brefill\b|ohne spule", name, re.I) else "spule"
    ean = str(prod.get("gtin13") or "")
    return {"name": name, "marke": ((prod.get("brand") or {}).get("name") or "").strip(), "preis_eur": preis,
            "normalpreis_eur": normal if normal and preis and normal > preis else preis, "gewicht_g": gew, "ausfuehrung": aus,
            "ean": ean if ean_ok(ean) else None, "artnr": prod.get("sku") or "", "verfuegbar": "InStock" in str(off.get("availability"))}


def verweise(url, h):
    """Andere Farben (Verweise derselben Marke) und Ausführungen (Spule/Refill) auf der Seite."""
    teil = urllib.parse.urlparse(url).path.strip("/").split("/")[0]
    out = set()
    for href in re.findall(r'href="(?:https://www\.3djake\.de)?/(' + re.escape(teil) + r'/[a-z0-9-]+)(?:\?sai=(\d+))?"', h):
        out.add(BASIS + href[0] + (f"?sai={href[1]}" if href[1] else ""))
    for sai in re.findall(r'name="ShopArticleItem_ID" value="(\d+)"', h):
        out.add(url.split("?")[0] + "?sai=" + sai)
    return out


def main():
    pfad = sys.argv[1]
    maxs = int(sys.argv[2]) if len(sys.argv) > 2 else 2500
    rows = [json.loads(l) for l in open(pfad, encoding="utf-8") if l.strip()]
    nach_url = {r["url"]: r for r in rows}
    serien = {}
    for r in rows:
        serien.setdefault(r["marke"].lower(), set()).add(r.get("serie") or "")
    offen = list(nach_url)
    gesehen, neu, alt_ok, fehler = set(), 0, 0, 0
    while offen and len(gesehen) < maxs:
        url = offen.pop(0)
        if url in gesehen:
            continue
        gesehen.add(url)
        try:
            h = holen(url)
        except Exception:
            fehler += 1
            time.sleep(PAUSE)
            continue
        x = lesen(url, h)
        for v in sorted(verweise(url, h)):
            if v not in gesehen and v not in offen:
                if "/bambu-lab/" in v:  # größte Marke zuerst: neue Bambu-Farben vor dem Rest
                    offen.insert(0, v)
                else:
                    offen.append(v)
        time.sleep(PAUSE)
        if not x or not x["preis_eur"]:
            continue
        r = nach_url.get(url)
        if r:  # bekannte Seite: nur Preise und Kennzahlen auffrischen, Serie und Farbe bleiben wie gepflegt
            r.update({k: x[k] for k in ("preis_eur", "normalpreis_eur") if x[k]})
            if x["ean"] and not r.get("ean"):
                r["ean"] = x["ean"]
            alt_ok += 1
            continue
        if "?sai=" not in url and 'name="ShopArticleItem_ID"' in h:
            continue  # Seite mit Ausführungen: die einzelnen Ausführungen (?sai=…) werden eigens gelesen
        if not re.search(r"\b(PLA|PETG|PCTG|ABS|ASA|TPU|PA|PC|PET|PVA|HIPS|PP)\b", x["name"], re.I):
            continue  # kein Filament (Zubehör, Drucker …)
        marke = x["marke"] or ""
        rest = re.sub(r",\s*(Spule|Refill|\d.*)$", "", x["name"][len(marke):].strip() if x["name"].lower().startswith(marke.lower()) else x["name"]).strip()
        serie = max((s for s in serien.get(marke.lower(), ()) if s and rest.lower().startswith(s.lower() + " ")), key=len, default="")
        farbe = rest[len(serie):].strip() if serie else ""
        if not serie or not farbe:
            continue  # nur Farben bekannter Serien übernehmen – sonst lieber nichts
        mat = re.search(r"\b(PLA|PETG|PCTG|ABS|ASA|TPU|PA\d*|PC|PET|PVA|HIPS|PP)\b", serie, re.I)
        r = {"marke": marke, "serie": serie, "material": mat.group(1).upper() if mat else serie.split()[0], "farbe": farbe,
             "ausfuehrung": x["ausfuehrung"], "url": url, "preis_eur": x["preis_eur"], "normalpreis_eur": x["normalpreis_eur"],
             "gewicht_g": x["gewicht_g"] or 1000, "durchmesser": 1.75, "ean": x["ean"], "artnr": x["artnr"], "herstellernr": None,
             "duese_min": None, "duese_max": None, "bett_min": None, "bett_max": None, "trocknen_c": None, "trocknen_h": None,
             "duese_hinweis": None, "anmerkung": "automatisch gefunden"}
        rows.append(r)
        nach_url[url] = r
        neu += 1
    with open(pfad, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"3DJake: {len(gesehen)} Seiten, {alt_ok} Preise aufgefrischt, {neu} neue Farben, {fehler} Fehler")


if __name__ == "__main__":
    main()
