#!/usr/bin/env python3
"""Logos der Hersteller von ihren Shop-Startseiten holen (nur wo robots.txt es erlaubt).
Kandidaten: <img> mit „logo“ in Klasse/Alt/Datei, Shopify-Header-Logo, og:image, apple-touch-icon.
Aufruf: logos_holen.py tools/logo_quellen.json <ziel>"""
import json, os, re, sys, urllib.parse, urllib.request, urllib.robotparser

UA = "Mozilla/5.0 (compatible; SchichtLohn-Logos/1.0; +https://github.com/MitKIprogrammieren/Schichtlohn)"


def erlaubt(url):
    u = urllib.parse.urlparse(url)
    rp = urllib.robotparser.RobotFileParser(f"{u.scheme}://{u.netloc}/robots.txt")
    try:
        rp.read()
    except Exception:
        return True
    return rp.can_fetch(UA, url)


def holen(url, roh=False):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=40) as r:
        b = r.read()
        return (b, r.headers.get("Content-Type", "")) if roh else b.decode("utf-8", "replace")


def kandidaten(html, basis, marke):
    out = []
    m = marke.lower().split()[0]
    for tag in re.findall(r"<img\b[^>]*>", html, re.I):
        src = re.search(r'\b(?:data-src|src)="([^"]+)"', tag) or re.search(r"\bsrcset=\"([^\" ,]+)", tag)
        if not src:
            continue
        t = tag.lower()
        if "logo" in t or m in t:
            out.append(src.group(1))
    for rel in (r'<link[^>]+rel="apple-touch-icon"[^>]+href="([^"]+)"', r'<meta[^>]+property="og:image"[^>]+content="([^"]+)"'):
        out += re.findall(rel, html, re.I)
    for s in re.findall(r'<svg\b[^>]*class="[^"]*logo[^"]*"[^>]*>.*?</svg>', html, re.I | re.S)[:1]:
        out.append("inline-svg:" + s)
    seen, erg = set(), []
    for c in out:
        if c.startswith("inline-svg:"):
            erg.append(c)
            continue
        c = c.replace("&amp;", "&")
        u = urllib.parse.urljoin(basis, c if not c.startswith("//") else "https:" + c)
        u = re.sub(r"([?&])width=\d+", r"\1width=800", u)
        if u not in seen:
            seen.add(u)
            erg.append(u)
    return erg[:6]


def main():
    quellen = json.load(open(sys.argv[1], encoding="utf-8"))
    ziel = sys.argv[2]
    os.makedirs(ziel, exist_ok=True)
    bericht = {}
    for slug, (marke, url) in quellen.items():
        try:
            if not erlaubt(url):
                bericht[slug] = "robots.txt verbietet den Abruf"
                continue
            html = holen(url)
            bericht[slug] = []
            for i, k in enumerate(kandidaten(html, url, marke)):
                try:
                    if k.startswith("inline-svg:"):
                        open(os.path.join(ziel, f"{slug}-{i}.svg"), "w").write(k[11:])
                        bericht[slug].append("inline-svg")
                        continue
                    if not erlaubt(k):
                        continue
                    b, typ = holen(k, roh=True)
                    endung = ".svg" if "svg" in typ else ".png" if "png" in typ else ".webp" if "webp" in typ else ".jpg"
                    open(os.path.join(ziel, f"{slug}-{i}{endung}"), "wb").write(b)
                    bericht[slug].append(k)
                except Exception as e:
                    bericht[slug].append(f"FEHLER {k}: {e}")
        except Exception as e:
            bericht[slug] = f"FEHLER {e}"
    json.dump(bericht, open(os.path.join(ziel, "bericht.json"), "w"), ensure_ascii=False, indent=1)
    print(json.dumps(bericht, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
