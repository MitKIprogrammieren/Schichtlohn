#!/usr/bin/env python3
"""Baut preise.json aus den vereinheitlichten Shopzeilen (tools/shops.py) und den 3DJake-Daten.
Aufruf: preise_bauen.py <ordner mit <shop>.jsonl> <ziel preise.json>

Format: {"stand", "shops": {schlüssel: [Name, Basis-URL]}, "z": [[shop, marke, titel, material, farbe, gewicht, refill, preis, normal, pfad, ean]]}
Die App ordnet die Zeilen selbst den Sorten im Lager zu (Marke, Material, Besonderheit, Farbe – oder EAN)."""
import json, os, sys, time

HIER = os.path.dirname(os.path.abspath(__file__))


def main():
    quelle, ziel = sys.argv[1], sys.argv[2]
    shops = json.load(open(os.path.join(HIER, "shops.json"), encoding="utf-8"))
    alle = {k: [v["name"], v["basis"].rstrip("/") + "/"] for k, v in shops.items()}
    alle["3djake"] = ["3DJake", "https://www.3djake.de/"]
    z = []

    def pfad(k, url):
        b = alle[k][1]
        return url[len(b):] if url.startswith(b) else url

    for k in shops:
        p = os.path.join(quelle, k + ".jsonl")
        if not os.path.exists(p):
            continue
        for l in open(p, encoding="utf-8"):
            if not l.strip():
                continue
            r = json.loads(l)
            if not r.get("preis_eur"):
                continue
            z.append([k, r["marke"], r["titel"], r["material"], r["farbe"], r["gewicht_g"], 1 if r["ausfuehrung"] == "refill" else 0,
                      round(r["preis_eur"], 2), round(r["normalpreis_eur"] or r["preis_eur"], 2), pfad(k, r["url"]), r.get("ean") or ""])
    for l in open(os.path.join(HIER, "haendler", "3djake.jsonl"), encoding="utf-8"):
        if not l.strip():
            continue
        r = json.loads(l)
        if not r.get("preis_eur") or (r.get("durchmesser") or 1.75) != 1.75:
            continue
        z.append(["3djake", r["marke"], f"{r['marke']} {r.get('serie') or ''} {r.get('farbe') or ''}".strip(), r.get("material") or "", r.get("farbe") or "",
                  r.get("gewicht_g") or 1000, 1 if r.get("ausfuehrung") == "refill" else 0, r["preis_eur"], r.get("normalpreis_eur") or r["preis_eur"],
                  pfad("3djake", r.get("url") or ""), r.get("ean") or ""])
    json.dump({"stand": time.strftime("%Y-%m-%d"), "shops": alle, "z": z}, open(ziel, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    print(len(z), "Angebote,", os.path.getsize(ziel) // 1024, "KB")


if __name__ == "__main__":
    main()
