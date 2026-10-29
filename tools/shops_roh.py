#!/usr/bin/env python3
"""Holt die Produktlisten der Herstellershops (Shopify: /products.json, WooCommerce: Store-API) roh nach <ziel>/<shop>.json.
Läuft in GitHub Actions (normales Internet). Aufruf: shops_roh.py tools/shops.json <ziel>"""
import json, os, sys, time, urllib.request

UA = "Mozilla/5.0 (compatible; SchichtLohn-Preise/1.0; +https://github.com/MitKIprogrammieren/Schichtlohn)"


def holen(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=40) as r:
        return json.loads(r.read().decode("utf-8"))


def shopify(basis, waehrung=""):
    alle = []
    for seite in range(1, 40):
        d = holen(f"{basis.rstrip('/')}/products.json?limit=250&page={seite}" + (f"&currency={waehrung}" if waehrung else ""))
        p = d.get("products") or []
        alle += p
        if len(p) < 250:
            break
        time.sleep(1)
    return alle


def woo(basis):
    alle = []
    for art in ("", "&type=variation"):
        for seite in range(1, 60):
            p = holen(f"{basis.rstrip('/')}/wp-json/wc/store/v1/products?per_page=100&page={seite}{art}")
            alle += p
            if len(p) < 100:
                break
            time.sleep(1)
    return alle


def wix(basis):
    """Wix-Shop: Produktseiten aus der Sitemap, Preis aus den Meta-Angaben (og/product:price)."""
    import re
    req = urllib.request.Request(basis.rstrip("/") + "/store-products-sitemap.xml", headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=40) as r:
        xml = r.read().decode("utf-8", "replace")
    out = []
    for u in re.findall(r"<loc>([^<]+)</loc>", xml):
        try:
            req = urllib.request.Request(u, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=40) as r:
                h = r.read().decode("utf-8", "replace")
        except Exception as e:
            out.append({"url": u, "fehler": str(e)})
            continue
        meta = dict(re.findall(r'<meta[^>]+property="([^"]+)"[^>]+content="([^"]*)"', h))
        titel = re.search(r"<title>([^<]*)</title>", h)
        preise = re.findall(r'"price":\s*"?([0-9]+(?:\.[0-9]+)?)', h)[:6]
        out.append({"url": u, "titel": titel.group(1) if titel else "", "meta": {k: v for k, v in meta.items() if k.startswith(("og:", "product:"))},
                    "preise_roh": preise})
        time.sleep(0.5)
    return out


def main():
    shops = json.load(open(sys.argv[1], encoding="utf-8"))
    ziel = sys.argv[2]
    os.makedirs(ziel, exist_ok=True)
    for k, s in shops.items():
        try:
            daten = (shopify(s["basis"], s.get("waehrung", "")) if s["art"] == "shopify" else woo(s["basis"]) if s["art"] == "woo"
                     else wix(s["basis"]))
            json.dump(daten, open(os.path.join(ziel, k + ".json"), "w", encoding="utf-8"), ensure_ascii=False)
            print(f"{k}: {len(daten)} Produkte")
        except Exception as e:
            print(f"{k}: FEHLER {e}")


if __name__ == "__main__":
    main()
