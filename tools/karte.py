#!/usr/bin/env python3
"""Baut homeassistant/schichtlohn-card.js neu aus index.html (Zeile SL_HTML).

Aus index.html wird alles ab <title> bis vor </body> übernommen; Kopf, Manifest und
Safe-Area-Stil entfallen, dafür wird window.__PW_HA=1 gesetzt.
Aufruf: python3 tools/karte.py [index.html] [karte.js]
"""
import json
import os
import re
import sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
KOPF = ('<!doctype html><html lang="de"><head><meta charset="utf-8"><meta name="viewport" '
        'content="width=device-width,initial-scale=1,viewport-fit=cover"><script>window.__PW_HA=1</script></head><body>')


def html_fuer_karte(index):
    zeilen = index.split("\n")
    a = next(i for i, z in enumerate(zeilen) if z.startswith("<title>"))
    e = max(i for i, z in enumerate(zeilen) if z.strip() == "</body>")
    while e > a and not zeilen[e - 1].strip():
        e -= 1
    return KOPF + "\n".join(zeilen[a:e]) + "\n</body></html>"


def main():
    idx = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "index.html")
    karte = sys.argv[2] if len(sys.argv) > 2 else os.path.join(ROOT, "homeassistant", "schichtlohn-card.js")
    html = html_fuer_karte(open(idx, encoding="utf-8").read())
    js = open(karte, encoding="utf-8").read()
    neu = "const SL_HTML=" + json.dumps(html, ensure_ascii=False).replace("</script", "<\\/script") + ";"
    js2, n = re.subn(r"^const SL_HTML=.*;$", lambda m: neu, js, count=1, flags=re.M)
    if n != 1:
        sys.exit("SL_HTML nicht gefunden")
    open(karte, "w", encoding="utf-8").write(js2)
    print("Karte aktualisiert:", os.path.normpath(karte))


if __name__ == "__main__":
    main()
