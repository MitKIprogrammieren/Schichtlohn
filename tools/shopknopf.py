#!/usr/bin/env python3
"""Baut die Zeile `const SL_SHOPKNOPF=…` in app/index.html aus tools/shopknopf.js (Knopf „An SchichtLohn senden“).
Kommentare und Einrückung fallen weg. Aufruf: python3 tools/shopknopf.py   (danach python3 tools/karte.py)"""
import json, os, re

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")


def kompakt(src):
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return "\n".join(z.strip() for z in src.split("\n") if z.strip())


def main():
    code = kompakt(open(os.path.join(ROOT, "tools", "shopknopf.js"), encoding="utf-8").read())
    pfad = os.path.join(ROOT, "app", "index.html")
    html = open(pfad, encoding="utf-8").read()
    zeile = "const SL_SHOPKNOPF=" + json.dumps(code, ensure_ascii=False).replace("</", "<\\/") + ";"
    neu, n = re.subn(r"^const SL_SHOPKNOPF=.*;$", lambda m: zeile, html, count=1, flags=re.M)
    if not n:
        raise SystemExit("Zeile const SL_SHOPKNOPF= nicht gefunden")
    open(pfad, "w", encoding="utf-8").write(neu)
    print("SL_SHOPKNOPF aktualisiert (%d Zeichen)" % len(code))


if __name__ == "__main__":
    main()
