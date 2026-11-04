#!/usr/bin/env python3
"""Holt die Produktlisten der Shops (Shopify: /products.json, WooCommerce: Store-API, Plentymarkets: /rest/io, JTL: Kategorieseiten, sonst Produktseiten aus der Sitemap) roh nach <ziel>/<shop>.json.
Läuft in GitHub Actions (normales Internet). Aufruf: shops_roh.py tools/shops.json <ziel> [shop1,shop2 – nur diese]"""
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


def _text(url, opener=None, accept="text/html"):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": accept, "Accept-Language": "de-DE,de;q=0.9", "Accept-Encoding": "gzip"})
    with (opener.open(req, timeout=60) if opener else urllib.request.urlopen(req, timeout=60)) as r:
        roh = r.read()
    if url.endswith(".gz") or roh[:2] == b"\x1f\x8b":
        import gzip
        roh = gzip.decompress(roh)
    return roh.decode("utf-8", "replace")


def _plenty_seite(url, op):
    """Deutscher Preis aus den Produktdaten (ld+json) der deutschen Produktseite – nur als Notlösung, die Seiten sind groß."""
    import re
    if not url:
        return None, None
    try:
        h = _text(url, op)
    except Exception:
        return None, None
    time.sleep(1)
    m = re.search(r'"offers"\s*:\s*\{.*?"priceCurrency"\s*:\s*"EUR".*?"price"\s*:\s*"([\d.]+)"', h, re.S)
    p = float(m.group(1)) if m else None
    ls = re.search(r'"price"\s*:\s*"([\d.]+)"\s*,\s*"priceCurrency"\s*:\s*"EUR"\s*,\s*"priceType"\s*:\s*"ListPrice"', h)
    return p, (float(ls.group(1)) if ls else p)


def plenty(basis, pfad="/de/filament-resin/filament/"):
    """Plentymarkets (3D Prima): Filament-Ausführungen aus der Sitemap, Daten über die Shop-Schnittstelle /rest/io/variations
    (je Abruf 20 Ausführungen: Farbe, Gewicht, EAN, verkäuflich). Den Preis liest es von der deutschen Produktseite,
    weil die Schnittstelle nicht die deutsche Preisliste liefert (Seiten komprimiert geladen)."""
    import http.cookiejar, re
    basis = basis.rstrip("/")
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    try:  # Sitzung über die deutsche Seite öffnen
        _text(basis + pfad.rstrip("/").rsplit("/", 2)[0] + "/", op)
    except Exception:
        pass
    idx = _text(basis + "/sitemap.xml", op, "application/xml")
    urls = {}
    for sm in re.findall(r"<loc>([^<]*Sitemap_item[^<]*)</loc>", idx):
        for u in re.findall(r"<loc>([^<]+)</loc>", _text(sm, op, "application/xml")):
            m = re.search(r"_(\d+)_(\d+)$", u)
            if m and (basis + pfad) in u and not re.search(r"3-?mm|2-85", u):
                urls[m.group(2)] = u
        time.sleep(1)
    ids, out = list(urls), []
    for i in range(0, len(ids), 20):
        teil = ids[i:i + 20]
        q = "&".join("variationIds[]=" + v for v in teil)
        try:
            d = json.loads(_text(f"{basis}/rest/io/variations?{q}", op, "application/json"))
        except Exception as e:
            out.append({"fehler": str(e), "ids": teil})
            time.sleep(2)
            continue
        for doc in (d.get("data") or {}).get("documents") or []:
            x = doc.get("data") or {}
            v = x.get("variation") or {}
            pr = (x.get("prices") or {}).get("default") or {}
            dat = pr.get("data") or {}
            mwst = (pr.get("vat") or {}).get("value")
            preis = (pr.get("price") or {}).get("value")
            rrp = ((x.get("prices") or {}).get("rrp") or {}) or {}
            normal = ((rrp.get("price") or {}).get("value")) if isinstance(rrp, dict) else None
            # Die Schnittstelle liefert nicht die deutschen Preise (eigene Preisliste für Deutschland, z. B. 12,90 statt 14,90 €) –
            # Preis daher immer von der deutschen Produktseite, nur Farbe, Gewicht und EAN aus der Schnittstelle.
            preis, normal = _plenty_seite(urls.get(str(v.get("id")), ""), op)
            attr = {}
            for a in x.get("attributes") or []:
                attr[(a.get("attribute") or {}).get("backendName", "").strip()] = ((a.get("value") or {}).get("names") or {}).get("name") or (a.get("value") or {}).get("backendName") or ""
            ean = next((b.get("code") for b in x.get("barcodes") or [] if b.get("type") == "GTIN_13" and str(b.get("code") or "").isdigit()), "")
            out.append({"id": v.get("id"), "url": urls.get(str(v.get("id")), ""), "name": (x.get("texts") or {}).get("name1") or "",
                        "variante": v.get("name") or "", "marke": ((x.get("item") or {}).get("manufacturer") or {}).get("externalName") or "",
                        "farbe": attr.get("od_color", ""), "dicke": attr.get("od_ size", ""), "gewicht": attr.get("od_weight", ""),
                        "preis": preis, "normal": normal, "mwst": mwst, "waehrung": pr.get("currency"), "ean": ean,
                        "verkaufbar": (x.get("filter") or {}).get("isSalable")})
        time.sleep(1)
    return out


def jtl(basis, kategorien):
    """JTL-Shop (iGo3D): Kategorieseiten blättern (…_s2, _s3 …) für Produkte und Preise, dann je Produktseite die Farben
    (alle Farben eines Produkts haben denselben Preis)."""
    import re, html as H
    basis = basis.rstrip("/")
    prod = {}
    for k in kategorien:
        for seite in range(1, 40):
            try:
                h = _text(f"{basis}/{k}" + (f"_s{seite}" if seite > 1 else ""))
            except Exception:
                break
            neu = 0
            for blk in re.split(r'<div\s+class="productbox-title"\s+itemprop="name">', h)[1:]:
                u = re.search(r'href="([^"]+)"[^>]*>\s*([^<]+?)\s*</a>', blk)
                p = re.search(r'<meta\s+itemprop="price"\s+content="([\d.]+)"', blk)
                w = re.search(r'<meta\s+itemprop="priceCurrency"\s+content="([A-Z]+)"', blk)
                if not u or not p:
                    continue
                url = u.group(1).split("?")[0]
                if url not in prod:
                    neu += 1
                    alt = re.search(r'class="[^"]*(?:price-uvp|old-price|instead)[^"]*"[^>]*>\s*(?:<[^>]+>\s*)*([\d.]+,\d{2})', blk)
                    prod[url] = {"url": url, "name": H.unescape(u.group(2)), "preis": float(p.group(1)), "waehrung": w.group(1) if w else "EUR",
                                 "normal": float(alt.group(1).replace(".", "").replace(",", ".")) if alt else None, "kategorie": k}
            time.sleep(1)
            if not neu:
                break
    out = []
    for p in prod.values():
        try:
            h = _text(p["url"])
        except Exception as e:
            p["fehler"] = str(e)
            out.append(p)
            continue
        farben = []
        for f in re.findall(r'class="variation swatches[^"]*"[^>]*\btitle="([^"]+)"', h) + re.findall(r'<option\s[^>]*class="variation[^"]*"[^>]*>\s*([^<]+?)\s*</option>', h):
            f = H.unescape(f).strip()
            if f and f not in farben:
                farben.append(f)
        e = re.search(r'itemprop="gtin13"\s[^>]*content="(\d{13})"', h)
        m = re.search(r'itemprop="brand"[^>]*>.*?itemprop="name"[^>]*content="([^"]+)"', h, re.S) or re.search(r'"brand"\s*:\s*\{[^}]*"name"\s*:\s*"([^"]+)"', h)
        p.update({"farben": farben, "ean": e.group(1) if e else "", "marke": H.unescape(m.group(1)) if m else ""})
        out.append(p)
        time.sleep(0.8)
    return out


def _sitemap_urls(url, tiefe=0):
    """Alle <loc> einer Sitemap, Sitemap-Indizes werden aufgelöst."""
    import re
    try:
        t = _text(url, accept="application/xml,text/xml,*/*")
    except Exception as e:
        print(f"  Sitemap {url}: {e}")
        return []
    locs = [u.strip() for u in re.findall(r"<loc>\s*(?:<!\[CDATA\[)?\s*([^<\]\s]+)", t)]
    if "<sitemapindex" in t and tiefe < 2:
        alle = []
        for u in locs:
            alle += _sitemap_urls(u, tiefe + 1)
            time.sleep(0.5)
        return alle
    return locs


def _ld_produkte(h, url):
    """Produkte aus ld+json (Product, ProductGroup mit hasVariant), sonst aus den Meta-Angaben."""
    import html as H, re
    out = []

    def offer(o):
        if isinstance(o, list):
            o = o[0] if o else {}
        if not isinstance(o, dict):
            return None, None
        if o.get("@type") == "AggregateOffer":
            return o.get("lowPrice") or o.get("price"), o.get("priceCurrency")
        return o.get("price"), o.get("priceCurrency") or (o.get("priceSpecification") or {}).get("priceCurrency")

    def verf(o):
        o = o[0] if isinstance(o, list) and o else o
        return str((o or {}).get("availability") or "") if isinstance(o, dict) else ""

    def marke(x):
        b = x.get("brand")
        return (b.get("name") if isinstance(b, dict) else b) or ""

    def prod(x, eltern=None):
        pr, cur = offer(x.get("offers"))
        if pr in (None, ""):
            return
        out.append({"name": H.unescape(x.get("name") or (eltern or {}).get("name") or ""), "marke": marke(x) or marke(eltern or {}),
                    "farbe": x.get("color") or "", "ean": str(x.get("gtin13") or x.get("gtin") or ""), "sku": str(x.get("sku") or ""),
                    "preis": float(str(pr).replace(",", ".")), "waehrung": cur or "", "url": url, "verfuegbar": verf(x.get("offers"))})

    for b in re.findall(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', h, re.S):
        try:
            d = json.loads(b.strip())
        except Exception:
            continue
        for x in (d if isinstance(d, list) else d.get("@graph", [d])):
            if not isinstance(x, dict):
                continue
            ty = x.get("@type")
            ty = ty if isinstance(ty, list) else [ty]
            if "ProductGroup" in ty:
                for v in x.get("hasVariant") or []:
                    prod(v, x)
            elif "Product" in ty:
                prod(x)
    if not out:
        m = dict(re.findall(r'<meta[^>]+property="([^"]+)"[^>]+content="([^"]*)"', h))
        if m.get("product:price:amount"):
            out.append({"name": H.unescape((m.get("og:title") or "").split("|")[0].strip()), "marke": "", "farbe": "", "ean": "", "sku": "",
                        "preis": float(m["product:price:amount"]), "waehrung": m.get("product:price:currency") or "", "url": url})
    return out


def seiten(cfg):
    """Shops ohne Schnittstelle: Produktseiten aus der Sitemap (gefiltert), Daten aus ld+json bzw. Meta-Angaben."""
    import re
    urls = []
    for sm in cfg["sitemaps"]:
        urls += _sitemap_urls(sm)
    mu = re.compile(cfg.get("muster") or ".")
    au = re.compile(cfg["ohne"]) if cfg.get("ohne") else None
    urls = list(dict.fromkeys(u for u in urls if mu.search(u) and not (au and au.search(u))))
    for a, b in (cfg.get("ersetzen") or {}).items():
        urls = [u.replace(a, b) for u in urls]
    urls = urls[: int(cfg.get("max") or 1500)]
    print(f"  {len(urls)} Seiten")
    out = []
    for u in urls:
        try:
            out += _ld_produkte(_text(u), u)
        except Exception as e:
            out.append({"url": u, "fehler": str(e)})
        time.sleep(float(cfg.get("pause") or 0.8))
    return out


def main():
    shops = json.load(open(sys.argv[1], encoding="utf-8"))
    ziel = sys.argv[2]
    os.makedirs(ziel, exist_ok=True)
    nur = set(sys.argv[3].split(",")) if len(sys.argv) > 3 and sys.argv[3] else None
    for k, s in shops.items():
        if nur and k not in nur:
            continue
        try:
            daten = (shopify(s["basis"], s.get("waehrung", "")) if s["art"] == "shopify" else woo(s["basis"]) if s["art"] == "woo"
                     else plenty(s["basis"], s.get("pfad") or "/de/filament-resin/filament/") if s["art"] == "plenty"
                     else jtl(s["basis"], s.get("kategorien") or []) if s["art"] == "jtl"
                     else seiten(s) if s["art"] == "seiten" else wix(s["basis"]))
            json.dump(daten, open(os.path.join(ziel, k + ".json"), "w", encoding="utf-8"), ensure_ascii=False)
            print(f"{k}: {len(daten)} Produkte")
        except Exception as e:
            print(f"{k}: FEHLER {e}")


if __name__ == "__main__":
    main()
