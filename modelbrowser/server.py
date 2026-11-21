"""ModelBrowser – Archiv für 3D-Druckmodelle (Proxmox-NUC).

Ablage: /daten/<Plattform>/<Modell>/ mit seite.html (SingleFile), Bilder/, Daten/, info.json.
Link-Import: single-file-cli mit Chromium speichert die Seite, Bilder werden aus der Seite gezogen.
"""
import base64, hashlib, hmac, json, os, re, secrets, shutil, subprocess, tempfile, threading, time, urllib.error, urllib.parse, urllib.request, uuid, zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = int(os.environ.get("PORT", "8091"))
DATEN = os.environ.get("DATEN", "/daten")
HTML = os.environ.get("HTML", "/srv/index.html")
CHROME = os.environ.get("CHROME", "/usr/bin/chromium-browser")
MAX_UPLOAD = 2 * 1024 ** 3
AUFTRAEGE = {}
SPERRE = threading.Lock()
TYPEN = {".html": "text/html; charset=utf-8", ".webp": "image/webp", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
         ".png": "image/png", ".gif": "image/gif", ".svg": "image/svg+xml", ".pdf": "application/pdf",
         ".json": "application/json", ".txt": "text/plain; charset=utf-8", ".stl": "model/stl",
         ".3mf": "model/3mf", ".step": "model/step", ".stp": "model/step"}
PLATTFORMEN = {"makerworld": "MakerWorld", "printables": "Printables", "cults3d": "Cults 3D", "youmagine": "YouMagine",
               "3dsets": "3D Sets", "stlflix": "STLFLIX", "thingiverse": "Thingiverse", "thangs": "Thangs", "myminifactory": "MyMiniFactory"}
UA = "ModelBrowser/1.1 (privates Modellarchiv)"
ERLAUBT = {"p", "br", "h1", "h2", "h3", "h4", "h5", "ul", "ol", "li", "b", "strong", "i", "em", "u", "a", "img",
           "blockquote", "code", "pre", "hr", "table", "thead", "tbody", "tr", "td", "th", "span", "div", "figure", "figcaption"}
LEER = {"br", "hr", "img"}
COOKIE_WEG = (b'<style>#onetrust-consent-sdk,#onetrust-banner-sdk,.onetrust-pc-dark-filter,#CybotCookiebotDialog,'
              b'#CybotCookiebotDialogBodyUnderlay,.cky-consent-container,.cky-overlay,#usercentrics-root,#didomi-host,'
              b'.qc-cmp2-container,.fc-consent-root,#cookiescript_injected,[id*="cookie-banner" i],[class*="cookie-banner" i],'
              b'[class*="CookieBanner"],[class*="cookieConsent" i],[id*="cookieConsent" i],[class*="cookie-consent" i],'
              b'[id*="cookie-consent" i],[class*="consent-banner" i]{display:none!important}'
              b'html,body{overflow:auto!important}</style>')
COOKIE_SKRIPT = ('<script nonce="mbcookie">addEventListener("DOMContentLoaded",function(){'
                 'document.querySelectorAll("div,section,aside,footer,dialog").forEach(function(e){try{'
                 'var s=getComputedStyle(e);if((s.position=="fixed"||s.position=="sticky")&&/cookie/i.test(e.textContent.slice(0,600))'
                 '&&e.textContent.length<3000)e.remove()}catch(x){}});'
                 'document.querySelectorAll("[class*=mask],[class*=overlay],[class*=backdrop]").forEach(function(e){try{'
                 'var s=getComputedStyle(e);if(s.position=="fixed"&&!e.textContent.trim())e.remove()}catch(x){}})});</script>')


def sauber(name):
    name = re.sub(r'[\\/:*?"<>|\x00-\x1f]', " ", str(name or "")).strip().strip(".")
    name = re.sub(r"\s+", " ", name)[:120]
    return name or "Ohne Namen"


def pfad(*teile):
    p = os.path.realpath(os.path.join(DATEN, *[sauber(t) for t in teile]))
    if not p.startswith(os.path.realpath(DATEN) + os.sep):
        raise ValueError("ungültiger Pfad")
    return p


def dateien(ordner):
    try:
        return sorted([{"name": n, "groesse": os.path.getsize(os.path.join(ordner, n)),
                        "zeit": int(os.path.getmtime(os.path.join(ordner, n)))}
                       for n in os.listdir(ordner) if os.path.isfile(os.path.join(ordner, n)) and not n.startswith(".")],
                      key=lambda d: d["name"].lower())
    except OSError:
        return []


def info_lesen(ordner):
    try:
        with open(os.path.join(ordner, "info.json"), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def info_schreiben(ordner, **werte):
    BAUM_ZWISCHEN["veraltet"] = True
    i = info_lesen(ordner)
    i.update({k: v for k, v in werte.items() if v})
    with open(os.path.join(ordner, "info.json"), "w", encoding="utf-8") as f:
        json.dump(i, f, ensure_ascii=False, indent=1)


def info_setzen(ordner, **werte):
    """Wie info_schreiben, aber leere Werte zählen auch (None entfernt den Schlüssel)."""
    BAUM_ZWISCHEN["veraltet"] = True
    i = info_lesen(ordner)
    for k, v in werte.items():
        if v is None:
            i.pop(k, None)
        else:
            i[k] = v
    with open(os.path.join(ordner, "info.json"), "w", encoding="utf-8") as f:
        json.dump(i, f, ensure_ascii=False, indent=1)


def suchtext(i):
    import html as h
    teile = [i.get("titel", ""), i.get("autor", ""), " ".join(i.get("tags") or []), i.get("notiz", ""), i.get("filament", ""),
             re.sub(r"<[^>]+>", " ", h.unescape(i.get("beschreibung", "")))[:1500]]
    return re.sub(r"\s+", " ", " ".join(teile)).lower()


# Die Übersicht liest jeden Modellordner von der DsCLoud – das dauert über das Netz einige Sekunden.
# Darum wird sie zwischengespeichert, im Hintergrund frisch gehalten und nach jeder Änderung neu gebaut.
BAUM_ZWISCHEN = {"daten": None, "zeit": 0, "veraltet": True}
BAUM_SPERRE = threading.Lock()


def baum():
    z = BAUM_ZWISCHEN
    if z["daten"] is not None and not z["veraltet"] and time.time() - z["zeit"] < 600:
        return z["daten"]
    with BAUM_SPERRE:
        if z["daten"] is not None and not z["veraltet"] and time.time() - z["zeit"] < 600:
            return z["daten"]
        z["veraltet"] = False
        z["daten"] = baum_lesen()
        z["zeit"] = time.time()
        return z["daten"]


def baum_frisch_halten():
    while True:
        try:
            BAUM_ZWISCHEN["veraltet"] = True
            baum()
        except Exception as e:
            print("Übersicht:", e, flush=True)
        time.sleep(45)


def baum_lesen():
    erg = []
    os.makedirs(DATEN, exist_ok=True)
    for p in sorted(os.listdir(DATEN), key=str.lower):
        pp = os.path.join(DATEN, p)
        if not os.path.isdir(pp) or p.startswith((".", "@", "#")):
            continue
        modelle = []
        for m in sorted(os.listdir(pp), key=str.lower):
            mp = os.path.join(pp, m)
            if not os.path.isdir(mp) or m.startswith((".", "@", "#")):
                continue
            bilder = dateien(os.path.join(mp, "Bilder"))
            i = info_lesen(mp)
            eigene = [b for b in bilder if b["name"].startswith("eigen_")]
            titelbild = (eigene[0] if i.get("status") == "gedruckt" and eigene else (bilder[0] if bilder else {})).get("name", "")
            modelle.append({"name": m, "bilder": len(bilder), "dateien": len(dateien(os.path.join(mp, "Daten"))) + len(i.get("nas") or []),
                            "titelbild": titelbild, "seite": os.path.exists(os.path.join(mp, "seite.html")),
                            "zeit": int(os.path.getmtime(mp)), "url": i.get("url", ""), "status": i.get("status", ""),
                            "bewertung": i.get("bewertung", 0), "update": bool(i.get("update") or i.get("eigene_veraltet")), "such": suchtext(i)})
        erg.append({"name": p, "modelle": modelle})
    return erg


def modell(p, m):
    o = pfad(p, m)
    if not os.path.isdir(o):
        return None
    return {"plattform": sauber(p), "name": sauber(m), "info": info_lesen(o),
            "seite": os.path.exists(os.path.join(o, "seite.html")),
            "bilder": dateien(os.path.join(o, "Bilder")), "dateien": dateien(os.path.join(o, "Daten")),
            "versionen": versionen(o)}


def versionen(o):
    v = os.path.join(o, "Versionen")
    try:
        namen = sorted((n for n in os.listdir(v) if os.path.isdir(os.path.join(v, n)) and not n.startswith(".")), reverse=True)
    except OSError:
        return []
    return [{"name": n, "dateien": dateien(os.path.join(v, n, "Daten"))} for n in namen]


def titel_sauber(t):
    import html as h
    t = h.unescape(str(t or "")).strip()
    for m in (r"\s*[|\-–]\s*(Free\s+)?3D\s+(Print(ing)?|Printable)\s+(Model|File|STL).*$", r"\s*[|\-–]\s*MakerWorld.*$",
              r"\s+by\s+[^|]+\|\s*Download.*$", r"\s*[|\-–]\s*Download\s+(free\s+)?(STL|3D).*$",
              r"\s*[|\-–]\s*(Printables|Cults3?D?|Thingiverse|YouMagine|Thangs|3D\s*Sets)(\.com)?\s*$",
              r"\s*[|\-–]\s*STL\s+file.*$"):
        t = re.sub(m, "", t, flags=re.I).strip()
    return t


def meta(html, name):
    import html as h
    for tag in re.finditer(r"<meta\b[^>]*>", html[:2000000], re.I):
        at = {k.lower(): (x or y or z) for k, x, y, z in
              re.findall(r'([\w:-]+)\s*=\s*(?:"([^"]*)"|\'([^\']*)\'|([^\s>"\']+))', tag.group(0))}
        if (at.get("property") or at.get("name") or "").lower() == name.lower():
            return h.unescape(at.get("content", "")).strip()
    return ""


def titel_aus_html(html):
    t = meta(html, "og:title")
    if not t:
        t = re.search(r"<title[^>]*>([^<]+)</title>", html, re.I)
        t = t.group(1) if t else ""
    return titel_sauber(t)


from html.parser import HTMLParser


class Saeuberer(HTMLParser):
    """Beschreibung auf harmlose Tags reduzieren (keine Skripte, Stile, Event-Handler)."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.raus, self.weg = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "iframe", "object", "noscript", "svg", "form"):
            self.weg += 1
            return
        if self.weg or tag not in ERLAUBT:
            return
        a = dict(attrs)
        zus = ""
        if tag == "a" and re.match(r"^https?://", a.get("href") or ""):
            zus = ' href="%s" target="_blank" rel="noopener noreferrer"' % a["href"].replace('"', "%22")
        if tag == "img":
            src = a.get("src") or a.get("data-src") or ""
            if not re.match(r"^(https?://|data:image/(png|jpe?g|webp|gif);)", src):
                return
            zus = ' src="%s" loading="lazy" alt=""' % src.replace('"', "%22")
        self.raus.append("<%s%s>" % (tag, zus))

    def handle_endtag(self, tag):
        if tag in ("script", "style", "iframe", "object", "noscript", "svg", "form"):
            self.weg = max(0, self.weg - 1)
            return
        if not self.weg and tag in ERLAUBT and tag not in LEER:
            self.raus.append("</%s>" % tag)

    def handle_data(self, d):
        if not self.weg:
            import html as h
            self.raus.append(h.escape(d))


def saeubern(html):
    if not html:
        return ""
    p = Saeuberer()
    try:
        p.feed(str(html).replace("&amp;nbsp;", " ").replace("&nbsp;", " "))
        p.close()
    except Exception:
        pass
    return "".join(p.raus)[:300000]


def json_skripte(html):
    for t in re.finditer(r'<script[^>]+type=["\']?application/(?:ld\+)?json["\']?[^>]*>(.*?)</script>', html, re.S | re.I):
        try:
            yield json.loads(t.group(1))
        except ValueError:
            continue


def finde(d, schluessel, tiefe=0):
    """Erstes Dict im JSON-Baum, das alle Schlüssel hat."""
    if tiefe > 12:
        return None
    if isinstance(d, dict):
        if all(k in d for k in schluessel):
            return d
        for v in d.values():
            r = finde(v, schluessel, tiefe + 1)
            if r is not None:
                return r
    elif isinstance(d, list):
        for v in d[:200]:
            r = finde(v, schluessel, tiefe + 1)
            if r is not None:
                return r
    return None


def daten_aus_html(html):
    """Titel, Autor, Beschreibung, Galerie, Profile – erst Seitendaten (JSON), sonst Meta-Tags."""
    d = {"titel": titel_aus_html(html), "beschreibung": "", "autor": "", "galerie": [], "profile": [], "tags": [], "stand": ""}
    for j in json_skripte(html):
        de = finde(j, ("title", "instances")) or finde(j, ("title", "designCreator"))
        if de:
            d["titel"] = titel_sauber(de.get("title")) or d["titel"]
            d["beschreibung"] = de.get("summary") or de.get("details") or ""
            cr = de.get("designCreator") or {}
            d["autor"] = cr.get("name") or cr.get("handle") or ""
            ext = de.get("designExtension") or {}
            for b in ext.get("design_pictures") or ext.get("designPictures") or []:
                u = b.get("url") if isinstance(b, dict) else b
                if u:
                    d["galerie"].append(u)
            if not d["galerie"] and de.get("coverUrl"):
                d["galerie"].append(de["coverUrl"])
            for i in de.get("instances") or []:
                zeit = i.get("prediction") or 0
                platten = i.get("plates") or ((i.get("extention") or {}).get("modelInfo") or {}).get("plates") or []
                d["profile"].append({"id": i.get("id"), "titel": titel_sauber(i.get("title")) or "Profil", "stunden": round(zeit / 3600, 1) if zeit else 0,
                                     "platten": len(platten) if isinstance(platten, list) else int(platten or 0),
                                     "gewicht": round(i.get("weight") or 0), "drucker": (i.get("compatibility") or {}).get("devModelName", "")})
            d["tags"] = [t if isinstance(t, str) else t.get("name", "") for t in (de.get("tags") or [])][:20]
            d["stand"] = str(de.get("updateTime") or de.get("updatedAt") or "")
            break
        if isinstance(j, dict) and j.get("@type") in ("Product", "CreativeWork", "3DModel", "Thing") and not d["beschreibung"]:
            d["beschreibung"] = j.get("description") or ""
            au = j.get("author") or j.get("creator") or {}
            if isinstance(au, list):
                au = au[0] if au else {}
            d["autor"] = au.get("name", "") if isinstance(au, dict) else str(au)
            bild = j.get("image")
            for u in (bild if isinstance(bild, list) else [bild]):
                if isinstance(u, dict):
                    u = u.get("url")
                if isinstance(u, str) and u.startswith("http"):
                    d["galerie"].append(u)
    if not d["beschreibung"]:
        d["beschreibung"] = meta(html, "og:description") or meta(html, "description")
        if d["beschreibung"]:
            import html as h
            d["beschreibung"] = "<p>" + h.escape(d["beschreibung"]) + "</p>"
    if not d["autor"]:
        d["autor"] = meta(html, "author")
    if not d["galerie"] and meta(html, "og:image").startswith("http"):
        d["galerie"].append(meta(html, "og:image"))
    d["beschreibung"] = saeubern(d["beschreibung"])
    gesehen, gal = set(), []
    for u in d["galerie"]:
        u = u.split("?")[0] if "makerworld" in u or "bblmw" in u else u
        if u not in gesehen:
            gesehen.add(u)
            gal.append(u)
    d["galerie"] = gal[:40]
    if "STLFLIX - The Ultimate" in d["titel"] or "stlflix" in (meta(html, "og:site_name") or "").lower():
        stlflix_daten(html, d)
    return d


def stlflix_daten(html, d):
    """STLFLIX liefert nur allgemeine Meta-Tags – Titel, Bilder und Beschreibung aus der fertigen Seite holen."""
    import html as h
    t = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.S)
    if t:
        d["titel"] = titel_sauber(re.sub(r"<[^>]+>", "", h.unescape(t.group(1)))).strip() or d["titel"]
    gal = []
    for u in re.findall(r"https://s3\.[a-z0-9-]+\.amazonaws\.com/static\.stlflix\.com/[^\"' )>]+?\.(?:jpe?g|png|webp)", html, re.I):
        if u not in gal and not re.search(r"(^|/)(thumbnail|small|medium)_", u):
            gal.append(u)
    d["galerie"] = gal[:40]
    d["beschreibung"] = ""
    i = html.find("MODEL DESCRIPTION")
    if i > 0:
        rest = html[i + len("MODEL DESCRIPTION"):]
        e = re.search(r"<h2[^>]*>\s*Filaments in this model|Filaments in this model|<h2", rest)
        stueck = rest[:e.start()] if e else rest[:60000]
        stueck = re.sub(r"^[^<]*>", "", stueck)
        d["beschreibung"] = re.sub(r"^(\s*</[^>]+>)+", "", saeubern(stueck[:120000]))
    tags = []
    for muster in (r"Drop:\s*(?:<[^>]+>\s*)*([^<]{2,60})", r"STL\s*#\s*(\d+)"):
        m = re.search(muster, html)
        if m:
            tags.append(("STL #" if muster.startswith("STL") else "") + m.group(1).strip())
    d["tags"] = tags
    d["autor"] = "STLFLIX"


def stlflix_produkte(html):
    """Alle Modell-Links einer STLFLIX-Drop-Seite."""
    links = []
    for s in re.findall(r"https://platform\.stlflix\.com/product/[a-z0-9-]+", html):
        if s not in links:
            links.append(s)
    return links


def bilder_laden(urls, ziel):
    """Galeriebilder (öffentliche Bild-Links der Seite) herunterladen."""
    os.makedirs(ziel, exist_ok=True)
    n = 0
    for i, u in enumerate(urls, 1):
        try:
            req = urllib.request.Request(u, headers={"User-Agent": UA, "Accept": "image/*"})
            with urllib.request.urlopen(req, timeout=30) as r:
                roh = r.read(15 * 1024 * 1024 + 1)
                typ = r.headers.get("Content-Type", "")
            if len(roh) > 15 * 1024 * 1024 or len(roh) < 500:
                continue
            endung = {"image/webp": "webp", "image/png": "png", "image/gif": "gif"}.get(typ.split(";")[0], "")
            if not endung:
                endung = (os.path.splitext(urllib.parse.urlparse(u).path)[1][1:].lower() or "jpg")[:4]
            with open(os.path.join(ziel, f"galerie_{i:02d}.{endung}"), "wb") as f:
                f.write(roh)
            n += 1
        except Exception as e:
            print("Bild nicht ladbar:", u, e, flush=True)
    return n


def url_aus_html(html):
    u = re.search(r"<!--\s*Page saved with SingleFile\s*\n\s*url:\s*(\S+)", html)
    if u:
        return u.group(1)
    u = re.search(r'<link[^>]+rel=["\']?canonical["\']?[^>]+href=["\']?([^"\'\s>]+)', html, re.I)
    return u.group(1) if u else ""


def plattform_aus_url(url):
    host = urllib.parse.urlparse(url).hostname or ""
    for k, v in PLATTFORMEN.items():
        if k in host:
            return v
    return sauber(host.replace("www.", "")) if host else "Sonstige"


def bilder_ziehen(html, ziel, min_bytes=25000):
    """Notlösung: große eingebettete Bilder (data:-URIs) aus der SingleFile-Seite schreiben."""
    os.makedirs(ziel, exist_ok=True)
    gesehen = {hashlib.sha1(open(os.path.join(ziel, d["name"]), "rb").read()).hexdigest() for d in dateien(ziel)}
    n = 0
    for t in re.finditer(r"data:image/(jpeg|jpg|png|webp|gif);base64,([A-Za-z0-9+/=]{%d,})" % (min_bytes * 4 // 3), html):
        try:
            roh = base64.b64decode(t.group(2))
        except Exception:
            continue
        h = hashlib.sha1(roh).hexdigest()
        if h in gesehen:
            continue
        gesehen.add(h)
        n += 1
        endung = {"jpeg": "jpg"}.get(t.group(1), t.group(1))
        with open(os.path.join(ziel, f"bild_{n:02d}.{endung}"), "wb") as f:
            f.write(roh)
        if n >= 24:
            break
    return n


def seite_ablegen(html_bytes, p=None, m=None, url=""):
    """Gespeicherte Seite einsortieren: Ordner, seite.html, Galerie, info.json."""
    html = html_bytes.decode("utf-8", "replace")
    url = url or url_aus_html(html)
    d = daten_aus_html(html)
    if "3dsets.com" in (url or ""):
        dreidsets_daten(html, d, url)
    elif "youmagine.com" in (url or ""):
        youmagine_daten(html, d)
    p = p or plattform_aus_url(url)
    m = m or d["titel"] or "Neues Modell"
    o = pfad(p, m)
    # Beim Neu-Einlesen den Ordnernamen an den sauberen Titel anpassen
    if d["titel"] and sauber(d["titel"]) != sauber(m) and os.path.isdir(o) and not os.path.exists(pfad(p, d["titel"])):
        neu = pfad(p, d["titel"])
        shutil.move(o, neu)
        o, m = neu, d["titel"]
    os.makedirs(os.path.join(o, "Daten"), exist_ok=True)
    with open(os.path.join(o, "seite.html"), "wb") as f:
        f.write(html_bytes)
    bild_ordner = os.path.join(o, "Bilder")
    os.makedirs(bild_ordner, exist_ok=True)
    for alt in dateien(bild_ordner):  # automatisch erzeugte Bilder ersetzen, eigene behalten
        if re.match(r"^(bild|galerie)_\d+\.", alt["name"]):
            os.remove(os.path.join(bild_ordner, alt["name"]))
    anzahl = bilder_laden(d["galerie"], bild_ordner) if d["galerie"] else 0
    if anzahl == 0:
        anzahl = bilder_ziehen(html, bild_ordner)
    info_schreiben(o, url=url, titel=d["titel"] or m, autor=d["autor"], beschreibung=d["beschreibung"],
                   profile=d["profile"], tags=d["tags"], gespeichert=time.strftime("%Y-%m-%d %H:%M"), stand=d["stand"],
                   anleitung=d.get("anleitung"), changelog=d.get("changelog"), version=d.get("version"),
                   version_datum=d.get("version_datum"), version_schluessel=d.get("version_schluessel"))
    info_setzen(o, update=None, stand_fp=None)
    return sauber(p), sauber(m), anzahl


def importieren(aid, url, p=None, m=None):
    a = AUFTRAEGE[aid]
    tmp = os.path.join(DATEN, ".tmp", aid)
    os.makedirs(tmp, exist_ok=True)
    datei = os.path.join(tmp, "seite.html")
    try:
        a["schritt"] = "Seite wird im Chrome geöffnet …"
        befehl = ["single-file", url, datei, f"--browser-executable-path={CHROME}",
                  '--browser-args=["--no-sandbox","--disable-dev-shm-usage","--lang=de-DE"]',
                  "--browser-wait-delay=5000", "--browser-load-max-time=90000", "--block-scripts=false",
                  "--browser-width=1400", "--browser-height=1000", "--compress-CSS=true"]
        r = subprocess.run(befehl, capture_output=True, text=True, timeout=240)
        if not os.path.exists(datei) or os.path.getsize(datei) < 5000:
            raise RuntimeError((r.stderr or r.stdout or "keine Seite gespeichert").strip()[-400:])
        with open(datei, "rb") as f:
            roh = f.read()
        text = roh.decode("utf-8", "replace")
        if re.search(r"Just a moment|cf-challenge|challenge-platform|Verify you are human", text[:200000], re.I) and len(roh) < 400000:
            raise RuntimeError("Die Seite hat den Bot-Schutz gezeigt. Bitte mit der SingleFile-Erweiterung speichern und hochladen.")
        t = (titel_aus_html(text) or "").strip()
        if plattform_aus_url(url) in ("STLFLIX", "3D Sets") and len(t) < 40 and \
                re.search(r"\b(log ?in|sign ?in|sign up|anmelden|registrieren|entrar|cadastr\w*)\b", t, re.I):
            raise RuntimeError("Die Seite zeigt nur die Anmeldung (Inhalt nur für Abonnenten). Bitte im eigenen Browser "
                               "angemeldet mit der SingleFile-Erweiterung speichern und über ••• → „SingleFile hochladen“ einspielen.")
        if re.search(r"platform\.stlflix\.com/drops?/", url) and not m:
            produkte = stlflix_produkte(text)
            if not produkte:
                raise RuntimeError("Auf der Drop-Seite wurden keine Modelle gefunden.")
            drop = (titel_aus_html(text) or "").strip()
            t = re.search(r"<h1[^>]*>(.*?)</h1>", text, re.S)
            drop = re.sub(r"<[^>]+>", "", t.group(1)).strip() if t else drop
            fertig, fehler = [], []
            for k, purl in enumerate(produkte, 1):
                unter = aid + "-" + str(k)
                AUFTRAEGE[unter] = {"id": unter, "url": purl, "status": "läuft", "schritt": "", "zeit": int(time.time())}
                a["schritt"] = f"Drop „{drop}“: Modell {k} von {len(produkte)} …"
                importieren(unter, purl)
                u = AUFTRAEGE.pop(unter, {})
                if u.get("status") == "fertig":
                    fertig.append((u.get("plattform"), u.get("modell")))
                    if drop:
                        o2 = pfad(u.get("plattform"), u.get("modell"))
                        i2 = info_lesen(o2)
                        tg = [x for x in (i2.get("tags") or []) if x != "Drop: " + drop] + ["Drop: " + drop]
                        info_setzen(o2, tags=tg)
                else:
                    fehler.append(purl.rsplit("/", 1)[-1])
            if not fertig:
                raise RuntimeError("Kein Modell aus dem Drop gespeichert: " + ", ".join(fehler))
            text = f"Drop „{drop}“: {len(fertig)} Modelle gespeichert" + (f", {len(fehler)} fehlgeschlagen" if fehler else "")
            a.update(status="fertig", schritt=text, plattform=fertig[0][0], modell=fertig[0][1])
            return
        a["schritt"] = "Bilder werden geladen …"
        p, m, n = seite_ablegen(roh, p, m, url=url)
        text = f"Gespeichert mit {n} Bildern"
        if p == "3D Sets":
            a["schritt"] = "Bauanleitung wird gespeichert …"
            try:
                t2 = anleitung_sichern(pfad(p, m), info_lesen(pfad(p, m)).get("titel") or m)
                text += (" + " + t2) if t2 else ""
            except Exception as e:
                text += " – Bauanleitung nicht geladen: " + str(e)
        profile = info_lesen(pfad(p, m)).get("profile") or []
        o = pfad(p, m)
        if p == "MakerWorld" and profile and profile[0].get("id") and (konten_lesen().get("makerworld") or {}).get("token") \
                and not dateien(os.path.join(o, "Daten")):
            a["schritt"] = "Standardprofil (3MF) wird geladen …"
            try:
                text += " + " + mw_profil_laden(o, profile[0]["id"])
            except Exception as e:
                text += " – 3MF nicht geladen: " + str(e)
        a.update(status="fertig", schritt=text, plattform=p, modell=m)
    except Exception as e:
        a.update(status="fehler", schritt=str(e))
        print("Import-Fehler:", url, e, flush=True)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def datei_hash(f):
    h = hashlib.sha1()
    with open(f, "rb") as x:
        for b in iter(lambda: x.read(1024 * 1024), b""):
            h.update(b)
    return h.hexdigest()


def hashes(ordner):
    return {d["name"]: datei_hash(os.path.join(ordner, d["name"])) for d in dateien(ordner)}


def nur_text(html):
    import html as h
    return re.sub(r"\s+", " ", h.unescape(re.sub(r"<[^>]+>", " ", html or ""))).strip()


def zahl(x):
    return str(x).replace(".", ",")


def aenderungen_finden(alt, neu, alt_daten, neu_daten, alt_bilder, neu_bilder):
    punkte, neue_ids = [], []
    ap = {str(p.get("id") or p.get("titel")): p for p in alt.get("profile") or []}
    np_ = {str(p.get("id") or p.get("titel")): p for p in neu.get("profile") or []}
    for k, p in np_.items():
        if k not in ap:
            neue_ids.append(k)
            werte = [zahl(p["stunden"]) + " h" if p.get("stunden") else "", f'{p["platten"]} Platte{"n" if p["platten"] != 1 else ""}' if p.get("platten") else "",
                     f'{p["gewicht"]} g' if p.get("gewicht") else ""]
            punkte.append({"art": "neu", "text": f'Profil „{p.get("titel")}“' + (" · " + " · ".join(w for w in werte if w) if any(werte) else "")})
        else:
            a, teile = ap[k], []
            if a.get("titel") != p.get("titel"):
                teile.append(f'Name „{a.get("titel")}“ → „{p.get("titel")}“')
            for feld, einheit in (("stunden", " h"), ("gewicht", " g"), ("platten", " Platten")):
                if (a.get(feld) or 0) != (p.get(feld) or 0):
                    teile.append(f"{zahl(a.get(feld) or 0)}{einheit} → {zahl(p.get(feld) or 0)}{einheit}")
            if teile:
                punkte.append({"art": "geaendert", "text": f'Profil „{p.get("titel")}“: ' + ", ".join(teile)})
    for k, p in ap.items():
        if k not in np_:
            punkte.append({"art": "entfernt", "text": f'Profil „{p.get("titel")}“'})
    for n, h in neu_daten.items():
        if not n.lower().endswith(".3mf"):
            continue
        if n not in alt_daten:
            punkte.append({"art": "neu", "text": f"Datei {n}"})
        elif alt_daten[n] != h:
            punkte.append({"art": "geaendert", "text": f"3MF {n} ist anders"})
    gleich = [n for n, h in neu_daten.items() if n.lower().endswith(".3mf") and alt_daten.get(n) == h]
    if gleich and not any(p["text"].startswith("3MF") for p in punkte):
        punkte.append({"art": "info", "text": "3MF unverändert: " + ", ".join(gleich)})
    neue_bilder = len(set(neu_bilder.values()) - set(alt_bilder.values()))
    weg_bilder = len(set(alt_bilder.values()) - set(neu_bilder.values()))
    if neue_bilder or weg_bilder:
        punkte.append({"art": "bilder", "text": ", ".join(x for x in (f"{neue_bilder} neue Bilder" if neue_bilder else "",
                                                                     f"{weg_bilder} Bilder entfernt" if weg_bilder else "") if x)})
    if (alt.get("titel") or "") != (neu.get("titel") or ""):
        punkte.append({"art": "geaendert", "text": f'Titel „{alt.get("titel")}“ → „{neu.get("titel")}“'})
    if nur_text(alt.get("beschreibung")) != nur_text(neu.get("beschreibung")):
        punkte.append({"art": "geaendert", "text": "Beschreibung wurde überarbeitet"})
    if alt.get("version_schluessel") and alt.get("version_schluessel") != neu.get("version_schluessel"):
        punkte.insert(0, {"art": "geaendert", "text": f'Version {alt.get("version") or "?"} → {neu.get("version") or "?"}'})
        bekannt = {(e.get("name"), e.get("datum")) for e in alt.get("changelog") or []}
        for e in neu.get("changelog") or []:
            if (e.get("name"), e.get("datum")) not in bekannt:
                punkte.insert(1, {"art": "neu", "text": f'{e.get("name")}: ' + "; ".join(e.get("notizen") or [])})
    if not punkte:
        punkte.append({"art": "info", "text": "Keine Unterschiede bei Profilen, Dateien, Bildern oder Beschreibung gefunden"})
    return punkte, neue_ids


def update_auftrag(aid, p, m):
    """Neue Version laden, alte unter Versionen/<Datum> sichern und Unterschiede festhalten."""
    a = AUFTRAEGE[aid]
    o = pfad(p, m)
    alt = info_lesen(o)
    daten = os.path.join(o, "Daten")
    vname = (alt.get("gespeichert") or time.strftime("%Y-%m-%d"))[:10]
    vdir = os.path.join(o, "Versionen")
    n = 2
    while os.path.exists(os.path.join(vdir, vname)):
        vname = (alt.get("gespeichert") or time.strftime("%Y-%m-%d"))[:10] + f" ({n})"
        n += 1
    ziel = os.path.join(vdir, vname)
    try:
        a["schritt"] = "Alte Version wird gesichert …"
        alt_daten, alt_bilder = hashes(daten), hashes(os.path.join(o, "Bilder"))
        os.makedirs(ziel)
        for f in ("info.json", "seite.html"):
            if os.path.exists(os.path.join(o, f)):
                shutil.copy2(os.path.join(o, f), os.path.join(ziel, f))
        if os.path.isdir(os.path.join(o, "Bilder")):
            shutil.copytree(os.path.join(o, "Bilder"), os.path.join(ziel, "Bilder"))
        if os.path.isdir(daten):
            shutil.move(daten, os.path.join(ziel, "Daten"))
        os.makedirs(daten, exist_ok=True)
        info_setzen(o, geladen=None)
    except Exception as e:
        a.update(status="fehler", schritt="Sichern fehlgeschlagen: " + str(e))
        return
    alt_daten_ordner = os.path.join(ziel, "Daten")
    try:
        unter = aid + "-seite"
        AUFTRAEGE[unter] = {"id": unter, "status": "läuft", "schritt": "", "zeit": int(time.time())}
        a["schritt"] = "Neue Version wird eingelesen …"
        importieren(unter, alt.get("url"), p, m)
        u = AUFTRAEGE.pop(unter, {})
        if u.get("status") != "fertig":
            raise RuntimeError(u.get("schritt") or "Einlesen fehlgeschlagen")
        p, m = u.get("plattform") or p, u.get("modell") or m
        o = pfad(p, m)
        daten = os.path.join(o, "Daten")
        alt_daten_ordner = os.path.join(o, "Versionen", vname, "Daten")
        neu = info_lesen(o)
        ids = {str(p2.get("id")) for p2 in neu.get("profile") or [] if p2.get("id")}
        schon = set((neu.get("geladen") or {}).keys())
        for pid in (alt.get("geladen") or {}):
            if pid in ids and pid not in schon:
                a["schritt"] = "3MF wird neu geladen …"
                try:
                    mw_profil_laden(o, pid)
                except Exception as e:
                    print("Profil beim Update nicht geladen:", pid, e, flush=True)
        hinweis = ""
        modelle = [d for d in dateien(daten) if re.search(r"\.(3mf|stl)$", d["name"], re.I)]
        for d in dateien(alt_daten_ordner):
            if not os.path.exists(os.path.join(daten, d["name"])) and (not modelle or not re.search(r"\.(3mf|stl)$", d["name"], re.I)):
                shutil.copy2(os.path.join(alt_daten_ordner, d["name"]), os.path.join(daten, d["name"]))
        if not modelle and any(re.search(r"\.(3mf|stl)$", d["name"], re.I) for d in dateien(alt_daten_ordner)):
            hinweis = ("Deine Modelldateien sind noch die alte Version – die neue bei 3D Sets selbst herunterladen" if p == "3D Sets"
                       else "Dateien nicht neu geladen – die bisherigen bleiben im Ordner „Daten“")
        neu = info_lesen(o)
        punkte, neue_ids = aenderungen_finden(alt, neu, alt_daten, hashes(daten), alt_bilder, hashes(os.path.join(o, "Bilder")))
        if hinweis:
            punkte.append({"art": "info", "text": hinweis})
        info_setzen(o, update=None, stand_fp=None, aenderungen={"datum": time.strftime("%d.%m.%Y"), "version": vname,
                                                 "punkte": punkte, "neue_profile": neue_ids})
        a.update(status="fertig", schritt=f"Update geladen · alte Version als „{vname}“ gesichert", plattform=p, modell=m)
    except Exception as e:
        # alles zurück wie vorher
        try:
            o = pfad(p, m)
            if os.path.isdir(alt_daten_ordner):
                shutil.rmtree(os.path.join(o, "Daten"), ignore_errors=True)
                shutil.move(alt_daten_ordner, os.path.join(o, "Daten"))
            vb = os.path.join(o, "Versionen", vname, "Bilder")
            if os.path.isdir(vb):
                shutil.rmtree(os.path.join(o, "Bilder"), ignore_errors=True)
                shutil.move(vb, os.path.join(o, "Bilder"))
            with open(os.path.join(o, "info.json"), "w", encoding="utf-8") as f:
                json.dump(alt, f, ensure_ascii=False, indent=1)
            shutil.rmtree(os.path.join(o, "Versionen", vname), ignore_errors=True)
        except Exception as e2:
            print("Zurücksetzen fehlgeschlagen:", e2, flush=True)
        a.update(status="fehler", schritt="Update fehlgeschlagen: " + str(e), plattform=p, modell=m)


def json_holen(url, timeout=40):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def text_holen(url, timeout=40):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def version_tupel(text):
    """Versionsnummer aus einem Text. „V8“ (Zylinder) ist keine Version – Nummern mit Punkt gehen vor."""
    t = text or ""
    mit_punkt = re.findall(r"v(?:ersion)?\s*(\d+(?:\.\d+)+)", t, re.I) or re.findall(r"(?<![\d.])(\d+\.\d+(?:\.\d+)*)\s*$", t)
    if mit_punkt:
        return tuple(int(x) for x in mit_punkt[-1].split("."))
    ohne = re.findall(r"(?:^|[\s_-])v(?:ersion)?\s*(\d+)\s*$", t, re.I)
    return (int(ohne[-1]),) if ohne else ()


def version_kleiner(a, b):
    """a < b, wobei v1 == v1.0 == v1.0.0 gilt."""
    a, b = list(a), list(b)
    n = max(len(a), len(b))
    return a + [0] * (n - len(a)) < b + [0] * (n - len(b))


def anleitung_link(html):
    """Link zur neuesten Bauanleitung (Google-Präsentation): „Build Guide“ mit der höchsten Version."""
    kandidaten = []
    for m in re.finditer(r'<a\b[^>]*href=["\']?(https://docs\.google\.com/presentation/d/([\w-]{20,})[^"\' >]*)[^>]*>(.*?)</a>', html, re.S | re.I):
        text = re.sub(r"<[^>]+>|\s+", " ", m.group(3)).strip()
        kandidaten.append((1 if re.search(r"build\s*guide", text, re.I) else 0, version_tupel(text), m.group(2), text))
    if not kandidaten:
        ids = re.findall(r"https://docs\.google\.com/presentation/d/([\w-]{20,})", html)
        return (ids[0], "") if ids else (None, "")
    kandidaten.sort(key=lambda k: (k[0], k[1]), reverse=True)
    return kandidaten[0][2], kandidaten[0][3]


def anleitung_laden(gid, ziel_ordner, name):
    """Öffentliche Google-Präsentation als PDF speichern (keine Modelldatei)."""
    os.makedirs(ziel_ordner, exist_ok=True)
    datei = os.path.join(ziel_ordner, sauber(name) + ".pdf")
    req = urllib.request.Request(f"https://docs.google.com/presentation/d/{gid}/export/pdf", headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=600) as r, open(datei + ".laden", "wb") as f:
        if "pdf" not in (r.headers.get("Content-Type") or ""):
            raise RuntimeError("keine PDF (Anleitung nicht öffentlich?)")
        shutil.copyfileobj(r, f, 1024 * 1024)
    os.replace(datei + ".laden", datei)
    return os.path.basename(datei)


def changelog_3dsets(html):
    """Changelog einer 3D-Sets-Produktseite: [{datum, name, version, notizen}], neueste zuerst."""
    i = html.find("product-changelog")
    teil = html[i:] if i >= 0 else ""
    txt = lambda x: re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", __import__("html").unescape(x or ""))).strip()
    liste = []
    for blk in re.split(r"changelog-item", teil)[1:61]:
        blk = blk[:30000]
        dm = re.search(r"<h6[^>]*>(.*?)</h6>", blk, re.S)
        pm = re.search(r"<p[^>]*>(.*?)</p>", blk, re.S)
        if not pm:
            continue
        d = re.search(r"(\d{1,2})\.\s*(\d{1,2})\.\s*(\d{4})", txt(dm.group(1)) if dm else "")
        ul = re.search(r"<ul[^>]*>(.*?)</ul>", blk, re.S)
        name = txt(pm.group(1))
        v = version_tupel(name)
        liste.append({"datum": f"{int(d.group(1)):02d}.{int(d.group(2)):02d}.{d.group(3)}" if d else "",
                      "name": name, "version": "v" + ".".join(map(str, v)) if v else "",
                      "notizen": [txt(li) for li in re.findall(r"<li[^>]*>(.*?)</li>", ul.group(1), re.S)][:30] if ul else []})
    return liste


def dreidsets_daten(html, d, url):
    """3D Sets: Titel, Bilder und Beschreibung aus dem Shop, dazu Changelog, Version und Bauanleitung."""
    import html as h
    slug = re.search(r"3dsets\.com/product/([^/?#\s]+)", url or "")
    if slug:
        try:
            p = (json_holen("https://3dsets.com/wp-json/wc/store/v1/products?slug=" + urllib.parse.quote(slug.group(1))) or [None])[0]
        except Exception as e:
            p = None
            print("3D-Sets-Shopdaten nicht lesbar:", e, flush=True)
        if p:
            d["titel"] = h.unescape(p.get("name") or "").replace("×", "x").strip() or d["titel"]
            d["galerie"] = [b.get("src") for b in p.get("images") or [] if b.get("src")][:40] or d["galerie"]
            d["beschreibung"] = saeubern(p.get("description") or p.get("short_description") or "") or d["beschreibung"]
            d["tags"] = [h.unescape(c.get("name") or "") for c in p.get("categories") or []
                         if c.get("slug") not in ("models", "models-favorite-products", "new-products")]
    d["autor"] = "3D Sets"
    gid, text = anleitung_link(html)
    if gid:
        d["anleitung"] = f"https://docs.google.com/presentation/d/{gid}/edit"
        d["anleitung_text"] = text
    cl = changelog_3dsets(html)
    if cl:
        d["changelog"] = cl
        d["version"] = cl[0]["version"] or cl[0]["name"]
        d["version_datum"] = cl[0]["datum"]
        d["version_schluessel"] = cl[0]["name"] + "|" + cl[0]["datum"]


def div_inhalt(html, start):
    """Inhalt des <div>, das bei start beginnt (verschachtelte divs mitgezählt)."""
    i = html.find(">", start) + 1
    tiefe, pos = 1, i
    for m in re.finditer(r"<(/?)div\b", html[i:]):
        tiefe += -1 if m.group(1) else 1
        if tiefe == 0:
            return html[i:i + m.start()]
    return html[i:i + 50000]


def youmagine_daten(html, d):
    """YouMagine: Bildergalerie, Beschreibung und Designer aus der Seite (Dateien gibt es nur angemeldet)."""
    gal = []
    for u in re.findall(r'data-yslider-url=["\']?([^"\' >]+)', html):
        u = u if u.startswith("http") else "https://youmagine.com" + u
        if u not in gal:
            gal.append(u)
    if gal:
        d["galerie"] = gal[:40]
    m = re.search(r'<div[^>]*class=["\']?prose max-w-none["\' >]', html)
    if m:
        d["beschreibung"] = saeubern(div_inhalt(html, m.start())) or d["beschreibung"]
    og = meta(html, "og:title")
    if og:
        d["titel"] = titel_sauber(og) or d["titel"]
    a = re.search(r'href=["\']?/users/([\w.-]+)["\' >][^<]*(?:<[^>]+>\s*)*([^<]{2,40})', html)
    if a and not d.get("autor"):
        d["autor"] = a.group(1)
    if re.search(r">\s*Giveaway\s*<", html):
        d["tags"] = list(dict.fromkeys((d.get("tags") or []) + ["kostenlos"]))


def anleitung_sichern(o, titel):
    """Bauanleitung als PDF in „Daten“ legen, wenn sie fehlt oder es eine neuere gibt."""
    i = info_lesen(o)
    link = i.get("anleitung") or ""
    if "/d/" not in link:
        return ""
    gid = link.split("/d/")[1].split("/")[0]
    name = "Bauanleitung – " + titel
    datei = os.path.join(o, "Daten", sauber(name) + ".pdf")
    if os.path.exists(datei) and i.get("anleitung_pdf") == gid:
        return ""
    anleitung_laden(gid, os.path.join(o, "Daten"), name)
    info_setzen(o, anleitung_pdf=gid)
    return "Bauanleitung gespeichert"


def katalog_3dsets(aid, kategorie="models"):
    """Alle Modelle aus dem 3D-Sets-Shop: Originalseite, Bilder, Beschreibung, Changelog, Bauanleitung.
    Lädt NIE Modelldateien – die kommen bei 3D Sets nur bewusst vom Nutzer."""
    import html as h
    a = AUFTRAEGE[aid]
    try:
        a["schritt"] = "Modellliste wird geholt …"
        produkte, seite = [], 1
        while True:
            teil = json_holen(f"https://3dsets.com/wp-json/wc/store/v1/products?per_page=100&page={seite}")
            produkte += teil
            if len(teil) < 100:
                break
            seite += 1
        produkte = [p for p in produkte if any(c.get("slug") == kategorie for c in p.get("categories") or [])]
        vorhanden = {}
        pp = os.path.join(DATEN, "3D Sets")
        if os.path.isdir(pp):
            for m in os.listdir(pp):
                u = info_lesen(os.path.join(pp, m)).get("url", "").rstrip("/")
                if u:
                    vorhanden[u] = m
        ok, fehler = 0, []
        for k, p in enumerate(produkte, 1):
            titel = h.unescape(p.get("name") or "").replace("×", "x").strip()
            url = (p.get("permalink") or "").rstrip("/") + "/"
            unter = f"{aid}-{k}"
            AUFTRAEGE[unter] = {"id": unter, "status": "läuft", "schritt": "", "zeit": int(time.time())}
            a["schritt"] = f"{k}/{len(produkte)}: {titel} …"
            importieren(unter, url, "3D Sets", vorhanden.get(url.rstrip("/")) or sauber(titel))
            u = AUFTRAEGE.pop(unter, {})
            if u.get("status") == "fertig":
                ok += 1
            else:
                fehler.append(titel)
                print("3D Sets nicht eingelesen:", titel, u.get("schritt"), flush=True)
            time.sleep(2)
        text = f"3D Sets: {ok} Modelle eingelesen" + (f" · Fehler bei {len(fehler)}: " + ", ".join(fehler) if fehler else "")
        a.update(status="fertig", schritt=text, plattform="3D Sets",
                 modell=sauber(h.unescape(produkte[0]["name"]).replace("×", "x")) if produkte else "")
    except Exception as e:
        a.update(status="fehler", schritt="3D-Sets-Katalog fehlgeschlagen: " + str(e))


# ---------------------------------------------------------------------------
# DsCLoud (NFS, nur lesend) – über libnfs im Benutzerraum, ohne Mount im Container
# ---------------------------------------------------------------------------
import ctypes

NAS_SERVER = os.environ.get("NAS_SERVER", "192.168.1.4")
NAS_EXPORT = os.environ.get("NAS_EXPORT", "/volume2/RC")
NAS_ORDNER = os.environ.get("NAS_ORDNER", "/RC-Modelle")
NAS_UNSICHTBAR = {".DS_Store", "@eaDir", "#recycle", "Thumbs.db", "desktop.ini"}
_LIBNFS = None


class _Dirent(ctypes.Structure):
    pass


_Dirent._fields_ = [("next", ctypes.POINTER(_Dirent)), ("name", ctypes.c_char_p), ("inode", ctypes.c_uint64),
                    ("type", ctypes.c_uint32), ("mode", ctypes.c_uint32), ("size", ctypes.c_uint64),
                    ("atime_s", ctypes.c_long), ("atime_us", ctypes.c_long),
                    ("mtime_s", ctypes.c_long), ("mtime_us", ctypes.c_long)]


class _Stat(ctypes.Structure):
    _fields_ = [(n, ctypes.c_uint64) for n in ("dev", "ino", "mode", "nlink", "uid", "gid", "rdev", "size", "blksize",
                                              "blocks", "atime", "mtime", "ctime", "atime_nsec", "mtime_nsec",
                                              "ctime_nsec", "used")]


def libnfs():
    global _LIBNFS
    if _LIBNFS:
        return _LIBNFS
    import ctypes.util
    name = ctypes.util.find_library("nfs") or "libnfs.so.14"
    try:
        lib = ctypes.CDLL(name)
    except OSError:
        subprocess.run(["apk", "add", "--no-cache", "libnfs"], capture_output=True, timeout=180)
        lib = ctypes.CDLL(ctypes.util.find_library("nfs") or "libnfs.so.14")
    v = ctypes.c_void_p
    lib.nfs_init_context.restype = v
    lib.nfs_destroy_context.argtypes = [v]
    lib.nfs_mount.argtypes = [v, ctypes.c_char_p, ctypes.c_char_p]
    lib.nfs_get_error.argtypes = [v]
    lib.nfs_get_error.restype = ctypes.c_char_p
    lib.nfs_opendir.argtypes = [v, ctypes.c_char_p, ctypes.POINTER(v)]
    lib.nfs_readdir.argtypes = [v, v]
    lib.nfs_readdir.restype = ctypes.POINTER(_Dirent)
    lib.nfs_closedir.argtypes = [v, v]
    lib.nfs_open.argtypes = [v, ctypes.c_char_p, ctypes.c_int, ctypes.POINTER(v)]
    lib.nfs_close.argtypes = [v, v]
    lib.nfs_stat64.argtypes = [v, ctypes.c_char_p, ctypes.POINTER(_Stat)]
    # libnfs 5.x: nfs_pread(nfs, fh, offset, count, buf)
    lib.nfs_pread.argtypes = [v, v, ctypes.c_uint64, ctypes.c_uint64, ctypes.c_void_p]
    _LIBNFS = lib
    return lib


NAS_LOKAL = os.environ.get("NAS_LOKAL", "/nas")  # RC-Modelle schreibgeschützt eingebunden (bevorzugt)


class LokalNas:
    """RC-Modelle als schreibgeschützt eingebundener Ordner – gleiche Schnittstelle wie Nas."""

    def _p(self, pfad):
        rest = pfad[len(NAS_ORDNER):] if pfad.startswith(NAS_ORDNER) else pfad
        return NAS_LOKAL + rest

    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass

    def schliessen(self):
        pass

    def liste(self, pfad):
        erg = []
        with os.scandir(self._p(pfad)) as it:
            for e in it:
                n = e.name
                if n in NAS_UNSICHTBAR or n.startswith("."):
                    continue
                st = e.stat()
                erg.append({"name": n, "ordner": e.is_dir(), "groesse": 0 if e.is_dir() else st.st_size, "zeit": int(st.st_mtime)})
        return sorted(erg, key=lambda x: x["name"].lower())

    def groesse(self, pfad):
        return os.path.getsize(self._p(pfad))

    def oeffnen(self, pfad):
        return _LokalDatei(open(self._p(pfad), "rb"))


class _LokalDatei:
    def __init__(self, f):
        self.f = f
        self.groesse = os.fstat(f.fileno()).st_size

    def __getattr__(self, n):
        return getattr(self.f, n)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.f.close()


def Nas():
    if os.path.isdir(NAS_LOKAL):
        return LokalNas()
    return NfsNas()


class NfsNas:
    """Eine NFS-Verbindung zur DsCLoud. Nur lesen – es gibt hier keine Schreibfunktion."""

    def __init__(self):
        self.lib = libnfs()
        self.ctx = self.lib.nfs_init_context()
        if not self.ctx or self.lib.nfs_mount(self.ctx, NAS_SERVER.encode(), NAS_EXPORT.encode()) != 0:
            fehler = self.lib.nfs_get_error(self.ctx).decode("utf-8", "replace") if self.ctx else "kein Kontext"
            self.schliessen()
            raise RuntimeError("DsCLoud nicht erreichbar: " + fehler)

    def schliessen(self):
        if self.ctx:
            self.lib.nfs_destroy_context(self.ctx)
            self.ctx = None

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.schliessen()

    def liste(self, pfad):
        d = ctypes.c_void_p()
        if self.lib.nfs_opendir(self.ctx, pfad.encode(), ctypes.byref(d)) != 0:
            raise RuntimeError("Ordner nicht lesbar: " + pfad)
        erg = []
        try:
            while True:
                e = self.lib.nfs_readdir(self.ctx, d)
                if not e:
                    break
                e = e.contents
                n = e.name.decode("utf-8", "replace")
                if n in (".", "..") or n in NAS_UNSICHTBAR or n.startswith("."):
                    continue
                erg.append({"name": n, "ordner": e.type == 2, "groesse": int(e.size), "zeit": int(e.mtime_s)})
        finally:
            self.lib.nfs_closedir(self.ctx, d)
        return sorted(erg, key=lambda x: x["name"].lower())

    def groesse(self, pfad):
        st = _Stat()
        if self.lib.nfs_stat64(self.ctx, pfad.encode(), ctypes.byref(st)) != 0:
            raise FileNotFoundError(pfad)
        return int(st.size)

    def oeffnen(self, pfad):
        return NasDatei(self, pfad)


class NasDatei:
    """Lesbare Datei auf der NAS (für zipfile und zum Ausliefern)."""

    def __init__(self, nas, pfad):
        self.nas, self.pos = nas, 0
        self.groesse = nas.groesse(pfad)
        fh = ctypes.c_void_p()
        if nas.lib.nfs_open(nas.ctx, pfad.encode(), os.O_RDONLY, ctypes.byref(fh)) != 0:
            raise RuntimeError("Datei nicht lesbar: " + pfad)
        self.fh = fh

    def read(self, n=-1):
        if n is None or n < 0:
            n = self.groesse - self.pos
        n = max(0, min(n, self.groesse - self.pos))
        teile, rest = [], n
        while rest > 0:
            stueck = min(rest, 1024 * 1024)
            buf = ctypes.create_string_buffer(stueck)
            r = self.nas.lib.nfs_pread(self.nas.ctx, self.fh, self.pos, stueck, buf)
            if r <= 0:
                break
            teile.append(buf.raw[:r])
            self.pos += r
            rest -= r
        return b"".join(teile)

    def seek(self, off, wo=0):
        self.pos = off if wo == 0 else self.pos + off if wo == 1 else self.groesse + off
        return self.pos

    def tell(self):
        return self.pos

    def seekable(self):
        return True

    def readable(self):
        return True

    def close(self):
        if self.fh:
            self.nas.lib.nfs_close(self.nas.ctx, self.fh)
            self.fh = None

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


MODELL_ENDUNGEN = (".zip", ".rar", ".7z", ".stl", ".3mf", ".step", ".stp", ".obj")
BILD_ENDUNGEN = (".jpg", ".jpeg", ".png", ".webp")


def nas_version(name):
    n = re.sub(r"\.(zip|rar|7z|stl|3mf|step|stp|obj|pdf)$", "", name, flags=re.I)
    n = re.sub(r"-\d{8}T\d{6}Z-\d+-\d+$", "", n)
    treffer = re.findall(r"(?:^|[_\s-]|\d)v(?:ersion)?\s*(\d+(?:\.\d+)+|\d+(?=$|[_\s-]))", n, re.I)
    treffer = [t for t in treffer if not re.fullmatch(r"8", t) or "." in t] if re.search(r"v8[_\s-]?engine", n, re.I) else treffer
    if not treffer:
        treffer = re.findall(r"v(\d+\.\d+(?:\.\d+)*)", n, re.I)
    return tuple(int(x) for x in treffer[-1].split(".")) if treffer else ()


def nas_titel(name):
    """Dateiname → lesbarer Titel (ohne Endung, Version, Zeitstempel)."""
    t = re.sub(r"\.(zip|rar|7z|stl|3mf|step|stp|obj|pdf)$", "", name, flags=re.I)
    t = re.sub(r"-\d{8}T\d{6}Z-\d+-\d+$", "", t)
    t = re.sub(r"\.[a-z0-9]{6,10}$", "", t)  # Kürzel wie .sdfds5d5
    t = re.sub(r"[_\s-]*v(?:ersion)?\s*\d+(?:\.\d+)*(_alt)?$", "", t, flags=re.I)
    t = t.replace("_", " ")
    return re.sub(r"\s+", " ", t).strip(" -") or name


def woerter(t):
    t = re.sub(r"(\d)x(\d)", r"\1x\2", t.lower().replace("×", "x"))
    w = set(re.findall(r"[a-z0-9]+", t)) - {"3d", "sets", "for", "the", "and", "model", "v1", "zip", "pack"}
    return {x for x in w if not re.fullmatch(r"v?\d+(\.\d+)+", x)}


def nas_zuordnen_3dsets(eintraege, modelle):
    """3D-Sets-Dateien den Shop-Modellen zuordnen. modelle: {ordnername: titel}. Ergebnis {ordnername|None: [eintrag]}"""
    erg = {}
    for e in eintraege:
        titel = nas_titel(e["name"])
        fw = woerter(titel)
        nr = re.search(r"model[\s_]*(\d+)", e["name"], re.I)
        best, bestwert = None, 0.0
        for ordner, mt in modelle.items():
            mw = woerter(mt)
            mnr = re.search(r"model\s*(\d+)", mt, re.I)
            if nr and (not mnr or mnr.group(1) != nr.group(1)):
                continue
            if not fw or not mw:
                continue
            gemeinsam = len(fw & mw)
            wert = gemeinsam / len(fw | mw)
            if mw <= fw:
                wert += 0.3  # alle Wörter des Modellnamens stehen im Dateinamen
            if wert > bestwert or (wert == bestwert and best and len(mt) < len(modelle[best])):
                best, bestwert = ordner, wert
        if bestwert < 0.55:  # zweiter Versuch: seltene gemeinsame Begriffe zählen (Zubehör heißt in Datei und Shop oft anders)
            import math
            stamm = lambda w: {x[:5].rstrip("s") for x in w if not x.isdigit()} - {"acces", "upgra", "kit", "with", "ranch", "landy", "bambo", "4x4"}
            alle = {o2: stamm(woerter(t2)) for o2, t2 in modelle.items()}
            df = {}
            for ws in alle.values():
                for x in ws:
                    df[x] = df.get(x, 0) + 1
            fs = stamm(fw)
            kand = []
            for ordner, ms in alle.items():
                if nr and nr.group(1) not in re.findall(r"\d+", modelle[ordner]):
                    continue  # Datei nennt eine Modellnummer, die im Shop-Titel nicht vorkommt
                gem = fs & ms
                punkte = sum(math.log(len(alle) / df[x]) for x in gem if df[x] <= 2)
                if punkte >= 1.5:
                    kand.append((punkte, -len(modelle[ordner]), ordner))
            if kand:
                kand.sort(reverse=True)
                best, bestwert = kand[0][2], 0.56
        erg.setdefault(best if bestwert >= 0.55 else None, []).append(e)
    return erg


def nas_vorschau(nas, o, eintraege):
    """Bilder und PDF-Anleitungen aus den ZIPs/Ordnern holen (nur kopieren, nichts auf der NAS ändern)."""
    bild_ordner, daten = os.path.join(o, "Bilder"), os.path.join(o, "Daten")
    hat_bilder = any(not d["name"].startswith("eigen_") for d in dateien(bild_ordner))
    n_bild, n_pdf = 0, 0
    for e in eintraege:
        kandidaten = []  # (name, lesen)
        if e["ordner"]:
            try:
                for f in nas.liste(e["pfad"]):
                    if not f["ordner"]:
                        kandidaten.append((f["name"], f["groesse"], ("datei", e["pfad"] + "/" + f["name"])))
            except Exception:
                pass
        elif e["name"].lower().endswith(".zip") and e["groesse"] < 8 * 1024 ** 3:
            try:
                with nas.oeffnen(e["pfad"]) as fh, zipfile.ZipFile(fh) as z:
                    for info in z.infolist():
                        if not info.is_dir() and "__MACOSX" not in info.filename:
                            kandidaten.append((os.path.basename(info.filename), info.file_size, ("zip", e["pfad"], info.filename)))
            except Exception as ex:
                print("ZIP nicht lesbar:", e["name"], ex, flush=True)
        elif e["name"].lower().endswith(".pdf"):
            kandidaten.append((e["name"], e["groesse"], ("datei", e["pfad"])))
        bilder = [k for k in kandidaten if k[0].lower().endswith(BILD_ENDUNGEN) and 20000 < k[1] < 15 * 1024 ** 2]
        bilder.sort(key=lambda k: (0 if re.search(r"cover|render|main|titel|preview|front", k[0], re.I) else 1, -k[1]))
        pdfs = [k for k in kandidaten if k[0].lower().endswith(".pdf") and k[1] < 120 * 1024 ** 2]

        def lesen(q):
            if q[0] == "datei":
                with nas.oeffnen(q[1]) as fh:
                    return fh.read()
            with nas.oeffnen(q[1]) as fh, zipfile.ZipFile(fh) as z:
                return z.read(q[2])

        if not hat_bilder:
            os.makedirs(bild_ordner, exist_ok=True)
            for name, _, q in bilder[:8]:
                try:
                    n_bild += 1
                    with open(os.path.join(bild_ordner, f"nas_{n_bild:02d}{os.path.splitext(name)[1].lower()}"), "wb") as f:
                        f.write(lesen(q))
                except Exception as ex:
                    print("Bild nicht kopiert:", name, ex, flush=True)
        for name, _, q in pdfs[:3]:
            ziel = os.path.join(daten, sauber(name))
            if os.path.exists(ziel):
                continue
            try:
                os.makedirs(daten, exist_ok=True)
                with open(ziel + ".laden", "wb") as f:
                    f.write(lesen(q))
                os.replace(ziel + ".laden", ziel)
                n_pdf += 1
            except Exception as ex:
                print("PDF nicht kopiert:", name, ex, flush=True)
    return n_bild, n_pdf


def nas_inhalt(nas, pfad, tiefe=3, rel=""):
    """Dateien eines Ordners auf der NAS (mit Unterordnern), höchstens 400."""
    erg = []
    try:
        for f in nas.liste(pfad):
            if f["ordner"]:
                if tiefe > 1:
                    erg += nas_inhalt(nas, pfad + "/" + f["name"], tiefe - 1, rel + f["name"] + "/")
            else:
                erg.append({"name": rel + f["name"], "pfad": pfad + "/" + f["name"], "groesse": f["groesse"]})
            if len(erg) >= 400:
                break
    except Exception as ex:
        print("NAS-Ordner nicht lesbar:", pfad, ex, flush=True)
    return erg[:400]


def nas_pfad_ok(p):
    return isinstance(p, str) and p.startswith(NAS_ORDNER + "/") and "/../" not in p + "/" and "\x00" not in p


def aufraeumen_nas(p, geschrieben):
    """Einträge, deren DsCLoud-Dateien inzwischen woanders zugeordnet sind (oder fehlen), bereinigen.
    Reine DsCLoud-Einträge ohne eigene Notizen wandern in den Papierkorb, sonst wird nur die Verknüpfung entfernt."""
    pp, n = os.path.join(DATEN, p), 0
    if not os.path.isdir(pp):
        return 0
    for m in os.listdir(pp):
        o = os.path.join(pp, m)
        i = info_lesen(o)
        if m in geschrieben or not i.get("nas"):
            continue
        eigenes = i.get("url") or i.get("notiz") or i.get("status") or i.get("bewertung") or \
            any(not d["name"].lower().endswith(".pdf") for d in dateien(os.path.join(o, "Daten"))) or \
            any(d["name"].startswith("eigen_") for d in dateien(os.path.join(o, "Bilder")))
        if i.get("quelle") == "DsCLoud" and not eigenes:
            os.makedirs(os.path.join(DATEN, ".papierkorb"), exist_ok=True)
            shutil.move(o, os.path.join(DATEN, ".papierkorb", f"{p} – {m} – {int(time.time())}"))
        else:
            info_setzen(o, nas=None, eigene_version=None, eigene_veraltet=None)
        n += 1
    return n


def cults_zuordnen(eintraege):
    """Bei Cults gekaufte Dateien (Ordner RC-Modelle/Cults) den Cults-Modellen zuordnen:
    „Download all“-ZIPs beginnen mit dem Kurznamen des Modells, Einzeldateien stehen in .cults_dateien.json."""
    modelle = {}
    for p in os.listdir(DATEN):
        pp = os.path.join(DATEN, p)
        if p.startswith((".", "@", "#")) or not os.path.isdir(pp):
            continue
        for m in os.listdir(pp):
            u = info_lesen(os.path.join(pp, m)).get("url") or ""
            k = re.search(r"cults3d\.com/[a-z]{2}/[^/]+/[^/]+/([^/?#]+)", u)
            if k:
                modelle[k.group(1).lower()] = (p, m)
    karte = {}
    for slug, namen in (json_lesen(os.path.join(DATEN, ".cults_dateien.json")) or {}).items():
        for n in namen:
            karte[re.sub(r"^slice ", "", n.lower())] = slug.lower()  # Cults zeigt manchmal „Slice “ vor dem Namen
    namen_da = {e["name"].lower() for e in eintraege}
    paare, ohne = {}, []
    for e in eintraege:
        n = e["name"].lower()
        basis = re.sub(r" \(\d+\)(?=\.[^.]+$)", "", n)  # „datei (1).zip“ = doppelter Download
        if basis != n and basis in namen_da:
            continue
        slug = karte.get(basis) or karte.get(re.sub(r"^slice ", "", basis)) or next((s2 for s2 in sorted(modelle, key=len, reverse=True) if basis.startswith(s2)), None)
        pm = modelle.get(slug or "")
        if pm:
            paare.setdefault(pm, []).append(e)
        else:
            ohne.append(e["name"])
    if ohne:
        print("Cults: ohne Zuordnung:", ", ".join(ohne[:30]), flush=True)
    return paare


def cults_schreiben(nas, paare):
    """Cults-Dateien an die Modelle hängen; Verknüpfungen aus anderen DsCLoud-Ordnern bleiben erhalten."""
    n = 0
    for (p, m), l in paare.items():
        o = pfad(p, m)
        if not os.path.isdir(o):
            continue
        for e in l:
            if e["ordner"] and "inhalt" not in e:
                e["inhalt"] = nas_inhalt(nas, e["pfad"])
        alt = [x for x in (info_lesen(o).get("nas") or []) if "/Cults/" not in (x.get("pfad") or "")]
        neu = [{"name": e["name"], "pfad": e["pfad"], "groesse": e["groesse"], "zeit": e["zeit"], "ordner": e["ordner"],
                "inhalt": e.get("inhalt") or [], "version": ""} for e in sorted(l, key=lambda e: e["name"].lower())]
        info_setzen(o, nas=alt + neu)
        n += 1
    return n


def nas_scan(aid=None, mit_vorschau=True):
    """RC-Modelle auf der DsCLoud einlesen: jeder Designer-Ordner eine Gruppe, jede ZIP/jeder Unterordner ein Modell.
    3DSets wird den Shop-Modellen zugeordnet. Auf der NAS wird nichts verändert."""
    a = AUFTRAEGE.get(aid) or {}
    gruppen_namen = {"3DSets": "3D Sets", "RC-Modelle": "RC-Modelle"}
    neu = zugeordnet = 0
    cults_paare = {}
    with Nas() as nas:
        a["schritt"] = "DsCLoud wird gelesen …"
        oben = nas.liste(NAS_ORDNER)
        gruppen = {"RC-Modelle": [dict(x, pfad=NAS_ORDNER + "/" + x["name"]) for x in oben
                                  if not x["ordner"] and x["name"].lower().endswith(MODELL_ENDUNGEN)]}
        for g in oben:
            if g["ordner"]:
                gruppen[g["name"]] = [dict(x, pfad=f'{NAS_ORDNER}/{g["name"]}/{x["name"]}') for x in nas.liste(f'{NAS_ORDNER}/{g["name"]}')
                                      if x["ordner"] or x["name"].lower().endswith(MODELL_ENDUNGEN + (".pdf",))]
        for g, eintraege in gruppen.items():
            p = gruppen_namen.get(g, g)
            if g == "Cults":
                cults_paare = cults_zuordnen(eintraege)
                continue
            elif g == "3DSets":
                pp = os.path.join(DATEN, "3D Sets")
                modelle = {}
                if os.path.isdir(pp):
                    for m in os.listdir(pp):
                        t = info_lesen(os.path.join(pp, m)).get("titel")
                        if t and info_lesen(os.path.join(pp, m)).get("url"):
                            modelle[m] = t
                zuordnung = nas_zuordnen_3dsets([e for e in eintraege if not e["name"].lower().endswith(".pdf")], modelle)
                # PDFs mit gleichem Namen wie eine ZIP gehören zu dieser
                for e in eintraege:
                    if e["name"].lower().endswith(".pdf"):
                        stamm = e["name"][:-4].lower()
                        for k, l in zuordnung.items():
                            if any(x["name"].lower().startswith(stamm) for x in l):
                                l.append(e)
                                break
                einzeln = zuordnung.pop(None, [])
                paare = list(zuordnung.items())
                buendel = {}
                for e in einzeln:  # Zubehör & Co.: eigenes Modell aus dem Dateinamen (ZIP + gleichnamige PDF zusammen)
                    buendel.setdefault(sauber(re.sub(r"\.pdf$", "", nas_titel(e["name"]), flags=re.I)).lower(), []).append(e)
                for l2 in buendel.values():
                    l2.sort(key=lambda e: e["name"].lower().endswith(".pdf"))
                    paare.append((sauber(re.sub(r"\.pdf$", "", nas_titel(l2[0]["name"]), flags=re.I)), l2))
            else:
                pp = os.path.join(DATEN, p)
                modelle = {}
                if os.path.isdir(pp):
                    for m in os.listdir(pp):
                        i0 = info_lesen(os.path.join(pp, m))
                        if i0.get("url") and i0.get("titel"):
                            modelle[m] = i0["titel"]
                zuordnung = nas_zuordnen_3dsets(eintraege, modelle) if modelle else {None: eintraege}
                paare = [(k, l) for k, l in zuordnung.items() if k]
                buendel = {}
                for e in zuordnung.get(None, []):
                    buendel.setdefault(sauber(nas_titel(e["name"])).lower(), []).append(e)
                paare += [(sauber(nas_titel(l[0]["name"])), l) for l in buendel.values()]
            geschrieben = set()
            for m, l in paare:
                geschrieben.add(sauber(m))
                for e in l:
                    if e["ordner"] and "inhalt" not in e:
                        e["inhalt"] = nas_inhalt(nas, e["pfad"])
                o = pfad(p, m)
                war_da = os.path.isdir(o)
                os.makedirs(os.path.join(o, "Daten"), exist_ok=True)
                i = info_lesen(o)
                l = sorted(l, key=lambda e: (nas_version(e["name"]), e["zeit"]), reverse=True)
                versionen = [v for v in (nas_version(e["name"]) for e in l) if v]
                eigene = "v" + ".".join(map(str, max(versionen))) if versionen else ""
                aktuell = version_tupel(i.get("version") or "")
                cl = i.get("changelog") or []
                if cl and version_tupel(cl[0].get("name") or ""):
                    aktuell = version_tupel(cl[0]["name"])  # neu berechnen (ältere Einträge lasen z. B. „V8“ als Version)
                    if i.get("version") != "v" + ".".join(map(str, aktuell)):
                        info_setzen(o, version="v" + ".".join(map(str, aktuell)))
                werte = {"nas": [{"name": e["name"], "pfad": e["pfad"], "groesse": e["groesse"], "zeit": e["zeit"],
                                  "ordner": e["ordner"], "inhalt": e.get("inhalt") or [], "version": "v" + ".".join(map(str, nas_version(e["name"]))) if nas_version(e["name"]) else ""}
                                 for e in l],
                         "eigene_version": eigene or None,
                         "eigene_veraltet": bool(versionen and aktuell and version_kleiner(max(versionen), aktuell)) or None}
                if not war_da:
                    werte.update(titel=nas_titel(l[0]["name"]), autor="3D Sets" if p == "3D Sets" else g,
                                 gespeichert=time.strftime("%Y-%m-%d %H:%M"), quelle="DsCLoud")
                    neu += 1
                else:
                    zugeordnet += 1
                info_setzen(o, **werte)
                if mit_vorschau and not war_da or mit_vorschau and not dateien(os.path.join(o, "Bilder")):
                    a["schritt"] = f"{p}: {m} – Vorschaubilder …"
                    try:
                        nas_vorschau(nas, o, l)
                    except Exception as ex:
                        print("Vorschau fehlgeschlagen:", m, ex, flush=True)
            weg = aufraeumen_nas(p, geschrieben)
            if weg:
                print(f"DsCLoud: {weg} veraltete Einträge in {p} aufgeräumt", flush=True)
        if cults_paare:
            zugeordnet += cults_schreiben(nas, cults_paare)
    text = f"DsCLoud eingelesen: {neu} Modelle neu, {zugeordnet} vorhandenen zugeordnet"
    if a:
        a.update(status="fertig", schritt=text, plattform="3D Sets", modell="")
    print(text, flush=True)
    return text


def cults_abfrage(query, zugang=None):
    """Cults-GraphQL (nur lesen) mit Benutzername + API-Schlüssel."""
    import base64
    z = zugang or (konten_lesen().get("cults") or {})
    if not z.get("user") or not z.get("key"):
        raise RuntimeError("Cults-Konto nicht verbunden")
    req = urllib.request.Request("https://cults3d.com/graphql", data=json.dumps({"query": query}).encode(),
                                 headers={"Content-Type": "application/json", "User-Agent": UA,
                                          "Authorization": "Basic " + base64.b64encode(f'{z["user"]}:{z["key"]}'.encode()).decode()})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            d = json.loads(r.read())
    except urllib.error.HTTPError as e:
        raise RuntimeError("Cults lehnt ab (Benutzername oder Schlüssel falsch?)" if e.code == 401 else f"Cults-Fehler {e.code}")
    if d.get("errors"):
        raise RuntimeError("Cults: " + "; ".join(x.get("message", "") for x in d["errors"])[:300])
    return d["data"]


def cults_text_html(t):
    """Cults-Beschreibung (Text mit [link](url)) in sauberes HTML."""
    import html as h
    t = h.escape(t or "")
    t = re.sub(r"\[creation [^\]]+\]", "", t)
    t = re.sub(r"\[([^\]]{1,80})\]\((https?://[^)\s]+)\)", r'<a href="\2">\1</a>', t)
    t = re.sub(r"(?<![\"=])(https?://[^\s<]+)", r'<a href="\1">\1</a>', t)
    absaetze = [a.strip().replace("\r", "").replace("\n", "<br>") for a in re.split(r"(?:\r?\n){2,}", t) if a.strip()]
    return "".join(f"<p>{a}</p>" for a in absaetze)


CULTS_FELDER = """name(locale:DE) url(locale:DE) slug description(locale:DE) tags(locale:DE) updatedAt publishedAt
    illustrations{imageUrl} creator{nick} license{name(locale:DE)} price(currency:EUR){cents}"""


def katalog_cults(aid):
    """Alle Cults-Käufe und -Downloads (Bestellungen) einlesen. Lädt keine Modelldateien (die API bietet keine)."""
    a = AUFTRAEGE[aid]
    try:
        a["schritt"] = "Cults-Bestellungen werden geholt …"
        modelle, off = [], 0
        while True:
            d = cults_abfrage("{myself{ordersBatch(limit:50,offset:%d){total results{createdAt price{cents} lines{creation{%s}}}}}}" % (off, CULTS_FELDER))
            b = d["myself"]["ordersBatch"]
            for o in b["results"]:
                for l in o.get("lines") or []:
                    if l.get("creation"):
                        modelle.append(dict(l["creation"], gekauft=o["createdAt"][:10]))
            off += 50
            if off >= b["total"] or not b["results"]:
                break
        gruppen = {g.lower(): g for g in os.listdir(DATEN) if not g.startswith(".") and os.path.isdir(os.path.join(DATEN, g))}
        vorhanden = {}
        for g in gruppen.values():
            for m in os.listdir(os.path.join(DATEN, g)):
                u = info_lesen(os.path.join(DATEN, g, m)).get("url", "")
                if "cults3d.com" in u:
                    vorhanden[u.split("/")[-1]] = (g, m)
        neu = 0
        for k, c in enumerate(modelle, 1):
            titel = (c.get("name") or "").strip()
            a["schritt"] = f"{k}/{len(modelle)}: {titel} …"
            nick = (c.get("creator") or {}).get("nick") or ""
            p, m = vorhanden.get(c.get("slug") or "-") or (gruppen.get(nick.lower(), "Cults 3D"), sauber(titel))
            o = pfad(p, m)
            war_da = os.path.isdir(o)
            os.makedirs(os.path.join(o, "Daten"), exist_ok=True)
            bilder = [i["imageUrl"] for i in c.get("illustrations") or [] if i.get("imageUrl")]
            if not any(d2["name"].startswith("galerie_") for d2 in dateien(os.path.join(o, "Bilder"))):
                bilder_laden(bilder[:40], os.path.join(o, "Bilder"))
            beschr = cults_text_html(c.get("description"))
            guides = list(dict.fromkeys(re.findall(r"https://docs\.google\.com/presentation/d/([\w-]{20,})", c.get("description") or "")))
            preis = ((c.get("price") or {}).get("cents") or 0) / 100
            info_schreiben(o, url=c.get("url"), titel=titel, autor=nick, beschreibung=beschr,
                           tags=(c.get("tags") or [])[:20] + ([("kostenlos" if not preis else f"{preis:.2f} €".replace(".", ","))]),
                           gespeichert=time.strftime("%Y-%m-%d %H:%M"), stand=c.get("updatedAt"), quelle="Cults",
                           gekauft=c.get("gekauft"), lizenz=(c.get("license") or {}).get("name"),
                           anleitung=f"https://docs.google.com/presentation/d/{guides[0]}/edit" if guides else None)
            for j, gid in enumerate(guides[:3]):
                name = "Bauanleitung – " + titel + (f" ({j + 1})" if len(guides) > 1 else "")
                if not os.path.exists(os.path.join(o, "Daten", sauber(name) + ".pdf")):
                    a["schritt"] = f"{k}/{len(modelle)}: Bauanleitung für {titel} …"
                    try:
                        anleitung_laden(gid, os.path.join(o, "Daten"), name)
                    except Exception as e:
                        print("Cults-Anleitung nicht geladen:", titel, e, flush=True)
            neu += not war_da
            time.sleep(0.5)
        a.update(status="fertig", schritt=f"Cults: {len(modelle)} Modelle eingelesen ({neu} neu)", plattform="Cults 3D", modell="")
    except Exception as e:
        a.update(status="fehler", schritt="Cults fehlgeschlagen: " + str(e))


KONTEN = os.path.join(DATEN, ".konten.json")
KONTO_SPERRE = threading.Lock()


def konten_lesen():
    try:
        with open(KONTEN, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def konten_schreiben(k):
    with KONTO_SPERRE:
        tmp = KONTEN + ".tmp"
        with open(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w", encoding="utf-8") as f:
            json.dump(k, f)
        os.replace(tmp, KONTEN)


def konten_status():
    k = konten_lesen()
    mw = k.get("makerworld") or {}
    return {"makerworld": {"verbunden": bool(mw.get("token")), "name": mw.get("name", ""), "geprueft": mw.get("geprueft", "")},
            "printables": {"bald": True},
            "cults": {"verbunden": bool((k.get("cults") or {}).get("key")), "name": (k.get("cults") or {}).get("name", ""),
                      "geprueft": (k.get("cults") or {}).get("geprueft", "")}}


def mw_anfrage(url, token, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json",
                                               "Authorization": "Bearer " + token, "Cookie": "token=" + token})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except ValueError:
            return e.code, {}
    except Exception as e:
        return 0, {"error": "nicht erreichbar: %s" % e}


def mw_verbinden(token):
    token = (token or "").strip().strip('"')
    t = re.search(r"(?:^|;\s*)token=([^;\s]+)", token)
    if t:
        token = t.group(1)
    if len(token) < 20:
        raise ValueError("Das sieht nicht wie ein MakerWorld-Token aus.")
    code, d = mw_anfrage("https://api.bambulab.com/v1/user-service/my/profile", token)
    if code == 0:
        raise ValueError("MakerWorld ist gerade nicht erreichbar – später nochmal versuchen.")
    if code != 200:
        raise ValueError("MakerWorld hat den Token abgelehnt (%s). Ist er abgelaufen oder unvollständig?" % code)
    name = d.get("name") or d.get("handle") or d.get("account") or str(d.get("uid", ""))
    k = konten_lesen()
    k["makerworld"] = {"token": token, "name": name, "geprueft": time.strftime("%Y-%m-%d %H:%M")}
    konten_schreiben(k)
    return name


BAMBU = "https://api.bambulab.com/v1/user-service"
ANMELDUNG = {}  # email -> {"tfa": key, "zeit": t}  (Passwort wird nie gespeichert)


def bambu_post(url, daten):
    req = urllib.request.Request(url, json.dumps(daten).encode(), {"User-Agent": UA, "Content-Type": "application/json",
                                                                    "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read() or b"{}"), r.headers
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}"), e.headers
        except ValueError:
            return e.code, {}, e.headers
    except Exception as e:
        return 0, {"message": "nicht erreichbar: %s" % e}, {}


def bambu_fehler(code, d):
    return "Bambu: " + str(d.get("message") or d.get("error") or d.get("msg") or f"Fehler {code}")


def mw_anmelden(email, passwort=None, code=None):
    """Anmeldung beim Bambu-Konto (MakerWorld): Passwort, Code per E-Mail oder 2FA. Gibt ('fertig', name) oder ('code'|'tfa', text)."""
    email = (email or "").strip()
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        raise ValueError("Bitte die E-Mail deines Bambu-Kontos eingeben.")
    offen = ANMELDUNG.get(email) or {}
    if code and offen.get("tfa"):
        c, d, kopf = bambu_post("https://bambulab.com/api/sign-in/tfa", {"tfaKey": offen["tfa"], "tfaCode": code.strip()})
        token = d.get("accessToken") or d.get("token") or ""
        if not token:
            for z in (kopf.get_all("Set-Cookie") if hasattr(kopf, "get_all") else []) or []:
                t = re.match(r"token=([^;]+)", z)
                if t:
                    token = t.group(1)
        if not token:
            raise ValueError(bambu_fehler(c, d))
    elif code:
        c, d, _ = bambu_post(BAMBU + "/user/login", {"account": email, "code": code.strip()})
        token = d.get("accessToken")
        if not token:
            raise ValueError(bambu_fehler(c, d) + " – Code falsch oder abgelaufen?")
    else:
        if not passwort:
            raise ValueError("Bitte das Passwort eingeben.")
        c, d, _ = bambu_post(BAMBU + "/user/login", {"account": email, "password": passwort, "apiError": ""})
        token = d.get("accessToken")
        art = d.get("loginType") or ""
        if not token and art == "verifyCode":
            c2, d2, _ = bambu_post(BAMBU + "/user/sendemail/code", {"email": email, "type": "codeLogin"})
            if c2 not in (200, 201, 204):
                raise ValueError(bambu_fehler(c2, d2))
            ANMELDUNG[email] = {"zeit": time.time()}
            return "code", f"Bambu hat dir einen Code an {email} geschickt."
        if not token and art == "tfa":
            ANMELDUNG[email] = {"tfa": d.get("tfaKey"), "zeit": time.time()}
            return "tfa", "Bitte den Code aus deiner Authenticator-App eingeben."
        if not token:
            raise ValueError(bambu_fehler(c, d) + " – E-Mail oder Passwort falsch?")
    ANMELDUNG.pop(email, None)
    return "fertig", mw_verbinden(token)


def mw_profil_laden(o, profil_id):
    """3MF eines MakerWorld-Druckprofils mit dem eigenen Konto herunterladen."""
    token = (konten_lesen().get("makerworld") or {}).get("token")
    if not token:
        raise RuntimeError("MakerWorld ist nicht verbunden (oben auf „Konten“).")
    code, d = mw_anfrage(f"https://makerworld.com/api/v1/design-service/instance/{int(profil_id)}/f3mf?type=download", token)
    if code in (401, 403):
        raise RuntimeError("MakerWorld: " + (d.get("error") or "Anmeldung abgelaufen") + " – bitte unter „Konten“ neu verbinden.")
    if code != 200 or not d.get("url"):
        raise RuntimeError("MakerWorld hat keinen Download geliefert (%s %s)" % (code, d.get("error", "")))
    name = sauber(d.get("name") or f"profil_{profil_id}")
    if not name.lower().endswith(".3mf"):
        name += ".3mf"
    ziel = os.path.join(o, "Daten")
    os.makedirs(ziel, exist_ok=True)
    datei = os.path.join(ziel, name)
    req = urllib.request.Request(d["url"], headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=300) as r, open(datei + ".laden", "wb") as f:
        shutil.copyfileobj(r, f, 1024 * 1024)
    os.replace(datei + ".laden", datei)
    geladen = dict(info_lesen(o).get("geladen") or {})
    geladen[str(int(profil_id))] = name
    info_setzen(o, geladen=geladen)
    try:
        stl_aus_3mf(datei, ziel)
    except Exception as e:
        print("STL aus 3MF fehlgeschlagen:", name, e, flush=True)
    return name


def profil_auftrag(aid, p, m, profil_id):
    a = AUFTRAEGE[aid]
    try:
        a["schritt"] = "3MF wird geladen …"
        name = mw_profil_laden(pfad(p, m), profil_id)
        a.update(status="fertig", schritt=f"{name} gespeichert", plattform=sauber(p), modell=sauber(m))
    except Exception as e:
        a.update(status="fehler", schritt=str(e), plattform=sauber(p), modell=sauber(m))


def teile_aus_3mf(quelle):
    """Liste (Name, Dreiecke) je Teil auf der Platte, Koordinaten wie im Slicer."""
    import xml.etree.ElementTree as ET
    NS = "{http://schemas.microsoft.com/3dmanufacturing/core/2015/02}"
    PR = "{http://schemas.microsoft.com/3dmanufacturing/production/2015/06}"
    with zipfile.ZipFile(quelle) as z:
        modelle = {}

        def lese(pfad):
            if pfad in modelle:
                return modelle[pfad]
            objs = {}
            with z.open(pfad.lstrip("/")) as f:
                for _, el in ET.iterparse(f):
                    if el.tag == NS + "object":
                        o = {"name": el.get("name") or "", "mesh": None, "comp": []}
                        mesh = el.find(NS + "mesh")
                        if mesh is not None:
                            v = [(float(x.get("x")), float(x.get("y")), float(x.get("z"))) for x in mesh.iter(NS + "vertex")]
                            t = [(int(x.get("v1")), int(x.get("v2")), int(x.get("v3"))) for x in mesh.iter(NS + "triangle")]
                            o["mesh"] = (v, t)
                        comps = el.find(NS + "components")
                        if comps is not None:
                            for c in comps.findall(NS + "component"):
                                o["comp"].append((c.get(PR + "path") or pfad, c.get("objectid"), c.get("transform")))
                        objs[el.get("id")] = o
                        el.clear()
            modelle[pfad] = objs
            return objs

        def matrix(t):
            if not t:
                return (1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0)
            return tuple(float(x) for x in t.split())

        def mal(a, b):  # erst a, dann b (3MF: Zeilenvektor * M)
            r = []
            for i in range(4):
                zeile = a[i * 3:i * 3 + 3] if i < 3 else a[9:12]
                for j in range(3):
                    s_ = zeile[0] * b[j] + zeile[1] * b[3 + j] + zeile[2] * b[6 + j]
                    if i == 3:
                        s_ += b[9 + j]
                    r.append(s_)
            return tuple(r)

        def dreiecke(pfad, oid, m, aus, tiefe=0):
            o = lese(pfad).get(oid)
            if not o or tiefe > 8:
                return
            if o["mesh"]:
                v, t = o["mesh"]
                tv = [(x * m[0] + y * m[3] + zz * m[6] + m[9], x * m[1] + y * m[4] + zz * m[7] + m[10],
                       x * m[2] + y * m[5] + zz * m[8] + m[11]) for x, y, zz in v]
                aus.extend((tv[a], tv[b], tv[c]) for a, b, c in t)
            for cp, cid, ct in o["comp"]:
                dreiecke(cp, cid, mal(matrix(ct), m), aus, tiefe + 1)

        haupt = "3D/3dmodel.model"
        lese(haupt)
        bambu_namen = {}  # Bambu Studio legt die Teilenamen in model_settings.config ab
        try:
            with z.open("Metadata/model_settings.config") as f:
                for o in ET.parse(f).getroot().iter("object"):
                    for md in o.findall("metadata"):
                        if md.get("key") == "name" and md.get("value"):
                            bambu_namen[o.get("id")] = md.get("value")
                            break
        except (KeyError, ET.ParseError):
            pass
        with z.open(haupt) as f:
            wurzel = ET.parse(f).getroot()
        teile = []
        items = wurzel.find(NS + "build")
        for nr, it in enumerate(items.findall(NS + "item") if items is not None else [], 1):
            oid = it.get("objectid")
            tri = []
            dreiecke(it.get(PR + "path") or haupt, oid, matrix(it.get("transform")), tri)
            if tri:
                name = bambu_namen.get(oid) or lese(it.get(PR + "path") or haupt).get(oid, {}).get("name") or f"Teil {nr}"
                teile.append((name, tri))
        return teile


def stl_schreiben(f, tri, auf_null=True):
    import struct
    mx = my = mz = 0.0
    if auf_null and tri:
        mx = min(min(p[0] for p in d) for d in tri); my = min(min(p[1] for p in d) for d in tri)
        mz = min(min(p[2] for p in d) for d in tri)
    f.write(b"ModelBrowser STL".ljust(80, b" "))
    f.write(struct.pack("<I", len(tri)))
    for a, b, c in tri:
        a = (a[0] - mx, a[1] - my, a[2] - mz); b = (b[0] - mx, b[1] - my, b[2] - mz); c = (c[0] - mx, c[1] - my, c[2] - mz)
        ux, uy, uz = b[0] - a[0], b[1] - a[1], b[2] - a[2]
        vx, vy, vz = c[0] - a[0], c[1] - a[1], c[2] - a[2]
        nx, ny, nz = uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx
        l = (nx * nx + ny * ny + nz * nz) ** 0.5 or 1.0
        f.write(struct.pack("<12fH", nx / l, ny / l, nz / l, *a, *b, *c, 0))


def stl_aus_3mf(quelle, ziel_ordner):
    """Jedes Teil einer 3MF als binäre STL speichern. Gibt die Dateinamen zurück."""
    basis = os.path.splitext(os.path.basename(quelle))[0]
    namen, gemacht = set(), []
    for name, tri in teile_aus_3mf(quelle):
        datei = sauber(f"{basis} - {sauber(name)}")
        n = 2
        while datei.lower() in namen:
            datei = sauber(f"{basis} - {sauber(name)} ({n})"); n += 1
        namen.add(datei.lower())
        ziel = os.path.join(ziel_ordner, datei + ".stl")
        with open(ziel + ".tmp", "wb") as f:
            stl_schreiben(f, tri)
        os.replace(ziel + ".tmp", ziel)
        gemacht.append(datei + ".stl")
    return gemacht


def vorschau_stl(quelle):
    """Ganze 3MF als eine STL für die 3D-Ansicht (zwischengespeichert)."""
    st = os.stat(quelle)
    schluessel = hashlib.sha1(f"{quelle}|{st.st_size}|{st.st_mtime}".encode()).hexdigest()
    cache = os.path.join(DATEN, ".cache")
    os.makedirs(cache, exist_ok=True)
    ziel = os.path.join(cache, schluessel + ".stl")
    if not os.path.exists(ziel):
        alle = [d for _, tri in teile_aus_3mf(quelle) for d in tri]
        with open(ziel + ".tmp", "wb") as f:
            stl_schreiben(f, alle)
        os.replace(ziel + ".tmp", ziel)
    return ziel


def stl_auftrag(aid, p, m, datei):
    a = AUFTRAEGE[aid]
    try:
        o = pfad(p, m)
        q = os.path.join(o, "Daten", sauber(datei))
        if not os.path.isfile(q) or not q.lower().endswith(".3mf"):
            raise RuntimeError("3MF-Datei nicht gefunden")
        a["schritt"] = "STL wird erzeugt …"
        namen = stl_aus_3mf(q, os.path.join(o, "Daten"))
        if not namen:
            raise RuntimeError("In der 3MF wurden keine Teile gefunden.")
        a.update(status="fertig", schritt=f"{len(namen)} STL-Datei(en) erzeugt", plattform=sauber(p), modell=sauber(m))
    except Exception as e:
        a.update(status="fehler", schritt="STL: " + str(e), plattform=sauber(p), modell=sauber(m))


EINST = os.path.join(DATEN, ".einstellungen.json")
SITZ = os.path.join(DATEN, ".sitzungen.json")
VERSUCHE = {}
OFFEN = {("GET", "/"), ("GET", "/index.html"), ("GET", "/gesund"), ("GET", "/api/status"),
         ("POST", "/api/anmelden"), ("POST", "/api/import"),
         ("GET", "/icon.svg"), ("GET", "/icon-180.png"), ("GET", "/icon-512.png")}


def json_lesen(pfad):
    try:
        with open(pfad, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def json_schreiben(pfad, daten):
    tmp = pfad + ".tmp"
    with open(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w", encoding="utf-8") as f:
        json.dump(daten, f)
    os.replace(tmp, pfad)


def pin_hash(pin, salz):
    return hashlib.pbkdf2_hmac("sha256", pin.encode(), bytes.fromhex(salz), 200000).hex()


def sitzung_neu():
    t = secrets.token_urlsafe(32)
    s = {k: v for k, v in json_lesen(SITZ).items() if v > time.time()}
    s[hashlib.sha256(t.encode()).hexdigest()] = time.time() + 180 * 86400
    json_schreiben(SITZ, s)
    return t


def sitzung_ok(t):
    if not t:
        return False
    return json_lesen(SITZ).get(hashlib.sha256(t.encode()).hexdigest(), 0) > time.time()


def mw_fingerabdruck(d):
    """Was sich bei einem echten Update ändert: Titel, Beschreibung und die Druckprofile des Erstellers."""
    ersteller = str(((d.get("designCreator") or {}).get("uid")) or "")
    profile = sorted((x.get("id"), x.get("profileId"), x.get("title")) for x in (d.get("instances") or [])
                     if not ersteller or str(((x.get("instanceCreator") or {}).get("uid")) or "") in ("", ersteller))
    roh = json.dumps([d.get("title"), d.get("summary"), profile], ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(roh.encode()).hexdigest()[:16] if (d.get("title") or profile) else ""


def updates_pruefen():
    """MakerWorld-Modelle mit dem öffentlichen Stand vergleichen."""
    neu = 0
    for p in os.listdir(DATEN):
        pp = os.path.join(DATEN, p)
        if p.startswith(".") or not os.path.isdir(pp):
            continue
        for m in os.listdir(pp):
            o = os.path.join(pp, m)
            i = info_lesen(o)
            if re.search(r"3dsets\.com/product/", i.get("url", "")) and os.path.isdir(o):
                try:
                    cl = changelog_3dsets(text_holen(i["url"]))
                except Exception as e:
                    print("Update-Prüfung fehlgeschlagen:", m, e, flush=True)
                    continue
                if cl:
                    schluessel = cl[0]["name"] + "|" + cl[0]["datum"]
                    if not i.get("version_schluessel"):
                        info_setzen(o, version_schluessel=schluessel, changelog=cl, version=cl[0]["version"] or cl[0]["name"],
                                    version_datum=cl[0]["datum"])
                    elif schluessel != i.get("version_schluessel") and not i.get("update"):
                        info_setzen(o, update=True)
                        neu += 1
                time.sleep(2)
                continue
            t = re.search(r"makerworld\.com/(?:[a-z-]+/)?models/(\d+)", i.get("url", ""))
            if not t or not os.path.isdir(o):
                continue
            try:
                req = urllib.request.Request(f"https://makerworld.com/api/v1/design-service/design/{t.group(1)}",
                                             headers={"User-Agent": UA, "Accept": "application/json"})
                with urllib.request.urlopen(req, timeout=30) as r:
                    d = json.loads(r.read())
            except Exception as e:
                print("Update-Prüfung fehlgeschlagen:", m, e, flush=True)
                continue
            # „updateTime“ ändert sich schon bei jedem Druck/Like – taugt nicht als Update-Zeichen.
            # Echte Änderung = der Ersteller ändert Beschreibung oder lädt Druckprofile (3MF) neu hoch/hinzu.
            fp = mw_fingerabdruck(d)
            if not fp:
                continue
            if not i.get("stand_fp"):
                # erster Abgleich nach der Umstellung: heutigen Stand merken, alte Fehlalarme zurücknehmen
                info_setzen(o, stand_fp=fp, update=None, stand=str(d.get("updateTime") or ""))
            elif fp != i.get("stand_fp") and not i.get("update"):
                info_setzen(o, update=True, stand=str(d.get("updateTime") or ""))
                neu += 1
            time.sleep(2)
    return neu


def update_schleife():
    time.sleep(120)
    while True:
        try:
            n = updates_pruefen()
            print(f"Update-Prüfung fertig, {n} neue Updates", flush=True)
            try:
                nas_scan()
            except Exception as e:
                print("DsCLoud-Abgleich:", e, flush=True)
        except Exception as e:
            print("Update-Prüfung:", e, flush=True)
        time.sleep(24 * 3600)


class StillerServer(ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request, client_address):
        import sys
        if isinstance(sys.exc_info()[1], (ConnectionResetError, BrokenPipeError, TimeoutError)):
            return  # Browser hat die Verbindung geschlossen – kein Fehler
        super().handle_error(request, client_address)


class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def senden(self, code, body, typ="application/json; charset=utf-8", kopf=None):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False)
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", typ)
        self.send_header("Content-Length", str(len(body)))
        kopf = dict(kopf or {})
        self.send_header("Cache-Control", kopf.pop("Cache-Control", "no-store"))
        for k, v in kopf.items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def datei_senden(self, f, herunterladen=False):
        typ = TYPEN.get(os.path.splitext(f)[1].lower(), "application/octet-stream")
        name = urllib.parse.quote(os.path.basename(f))
        if f.endswith("seite.html") and not herunterladen:
            with open(f, "rb") as d:
                roh = d.read()
            zusatz = COOKIE_WEG + COOKIE_SKRIPT.encode()
            i = roh.lower().find(b"</head>")
            roh = roh[:i] + zusatz + roh[i:] if i >= 0 else zusatz + roh
            return self.senden(200, roh, typ, {"Content-Security-Policy": "script-src 'nonce-mbcookie'; object-src 'none'; frame-src 'none'; form-action 'none'",
                                               "Cache-Control": "private, max-age=60"})
        groesse = os.path.getsize(f)
        self.send_response(200)
        self.send_header("Content-Type", typ)
        self.send_header("Content-Length", str(groesse))
        self.send_header("Cache-Control", "private, max-age=300")
        self.send_header("Content-Disposition", f"{'attachment' if herunterladen else 'inline'}; filename*=UTF-8''{name}")
        self.end_headers()
        with open(f, "rb") as d:
            shutil.copyfileobj(d, self.wfile, 1024 * 1024)

    def sitzung(self):
        for teil in (self.headers.get("Cookie") or "").split(";"):
            k, _, v = teil.strip().partition("=")
            if k == "mb_sitzung":
                return v
        return ""

    def erlaubt(self, methode, pfad):
        if (methode, pfad) in OFFEN:
            return True
        if sitzung_ok(self.sitzung()):
            return True
        self.senden(401, {"ok": False, "anmelden": True, "text": "Bitte anmelden"})
        return False

    def zip_senden(self, o, name):
        dat = dateien(os.path.join(o, "Daten"))
        with tempfile.TemporaryFile(dir=os.path.join(DATEN, ".tmp")) as tmp:
            with zipfile.ZipFile(tmp, "w", zipfile.ZIP_STORED) as z:
                for d in dat:
                    z.write(os.path.join(o, "Daten", d["name"]), d["name"])
            groesse = tmp.tell()
            tmp.seek(0)
            self.send_response(200)
            self.send_header("Content-Type", "application/zip")
            self.send_header("Content-Length", str(groesse))
            self.send_header("Content-Disposition", "attachment; filename*=UTF-8''" + urllib.parse.quote(name + ".zip"))
            self.end_headers()
            shutil.copyfileobj(tmp, self.wfile, 1024 * 1024)

    def nas_senden(self, p):
        """Datei von der DsCLoud durchreichen (nur lesen)."""
        try:
            nas = Nas()
        except Exception as e:
            return self.senden(502, {"ok": False, "text": str(e)})
        try:
            with nas.oeffnen(p) as fh:
                name = p.rsplit("/", 1)[-1]
                self.send_response(200)
                self.send_header("Content-Type", "application/octet-stream")
                self.send_header("Content-Length", str(fh.groesse))
                self.send_header("Content-Disposition", "attachment; filename*=UTF-8''" + urllib.parse.quote(name))
                self.end_headers()
                while True:
                    b = fh.read(4 * 1024 * 1024)
                    if not b:
                        break
                    self.wfile.write(b)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except FileNotFoundError:
            return self.senden(404, {"ok": False})
        finally:
            nas.schliessen()

    def icon_senden(self, name):
        """App-Symbol aus dem Code-Ordner; fehlt es, einmal vom selben Commit holen."""
        ordner = os.path.dirname(HTML)
        f = os.path.join(ordner, name)
        if not os.path.exists(f):
            try:
                sha = open(os.path.join(ordner, "STAND")).read().strip()
                repo = os.environ.get("REPO", "MitKIprogrammieren/Schichtlohn")
                req = urllib.request.Request(f"https://cdn.jsdelivr.net/gh/{repo}@{sha}/modelbrowser/{name}", headers={"User-Agent": UA})
                with urllib.request.urlopen(req, timeout=20) as r:
                    daten = r.read()
                with open(f + ".tmp", "wb") as x:
                    x.write(daten)
                os.replace(f + ".tmp", f)
            except Exception:
                return self.senden(404, {"ok": False})
        with open(f, "rb") as x:
            daten = x.read()
        return self.senden(200, daten, "image/svg+xml" if name.endswith(".svg") else "image/png")

    def json_body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}") if n < 1_000_000 else {}

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        q = dict(urllib.parse.parse_qsl(u.query))
        if not self.erlaubt("GET", u.path):
            return
        try:
            if u.path == "/api/status":
                e = json_lesen(EINST)
                return self.senden(200, {"angemeldet": sitzung_ok(self.sitzung()), "pin": bool(e.get("pin"))})
            if u.path.startswith("/zip/") or u.path.startswith("/vorschau/"):
                teile = [urllib.parse.unquote(t) for t in u.path.split("/")[2:]]
                if len(teile) < 2 or any(t in ("", ".", "..") for t in teile):
                    return self.senden(404, {"ok": False})
                o = pfad(teile[0], teile[1])
                if u.path.startswith("/zip/"):
                    os.makedirs(os.path.join(DATEN, ".tmp"), exist_ok=True)
                    v = q.get("v", "")
                    if v:
                        if v in (".", "..") or "/" in v or not os.path.isdir(os.path.join(o, "Versionen", v)):
                            return self.senden(404, {"ok": False})
                        return self.zip_senden(os.path.join(o, "Versionen", v), sauber(teile[1]) + " – Version " + v)
                    return self.zip_senden(o, sauber(teile[1]))
                f = os.path.join(o, "Daten", sauber(teile[2]) if len(teile) > 2 else "")
                if not os.path.isfile(f):
                    return self.senden(404, {"ok": False})
                if f.lower().endswith(".3mf"):
                    f = vorschau_stl(f)
                return self.datei_senden(f)
            if u.path in ("/", "/index.html"):
                with open(HTML, "rb") as f:
                    return self.senden(200, f.read(), "text/html; charset=utf-8")
            if u.path == "/nas":
                p = q.get("pfad", "")
                if not nas_pfad_ok(p):
                    return self.senden(404, {"ok": False})
                return self.nas_senden(p)
            if u.path in ("/icon.svg", "/icon-180.png", "/icon-512.png"):
                return self.icon_senden(u.path[1:])
            if u.path == "/gesund":
                return self.senden(200, {"ok": True})
            if u.path == "/api/baum":
                return self.senden(200, baum())
            if u.path == "/api/modell":
                d = modell(q.get("p"), q.get("m"))
                return self.senden(200 if d else 404, d or {"ok": False})
            if u.path == "/api/konten":
                return self.senden(200, konten_status())
            if u.path == "/api/auftraege":
                return self.senden(200, list(AUFTRAEGE.values())[-20:])
            if u.path.startswith("/d/"):
                teile = [urllib.parse.unquote(t) for t in u.path[3:].split("/")]
                if len(teile) < 3 or any(t in ("", ".", "..") for t in teile):
                    return self.senden(404, {"ok": False})
                f = os.path.realpath(os.path.join(pfad(teile[0], teile[1]), *teile[2:]))
                if not f.startswith(os.path.realpath(DATEN) + os.sep) or not os.path.isfile(f):
                    return self.senden(404, {"ok": False})
                return self.datei_senden(f, "dl" in q)
        except ValueError as e:
            return self.senden(400, {"ok": False, "text": str(e)})
        self.senden(404, {"ok": False})

    def do_PUT(self):
        BAUM_ZWISCHEN["veraltet"] = True
        u = urllib.parse.urlparse(self.path)
        q = dict(urllib.parse.parse_qsl(u.query))
        if not self.erlaubt("PUT", u.path):
            return
        if u.path != "/api/hochladen":
            return self.senden(404, {"ok": False})
        n = int(self.headers.get("Content-Length") or 0)
        if n <= 0 or n > MAX_UPLOAD:
            return self.senden(413, {"ok": False, "text": "Datei fehlt oder ist zu groß"})
        art = q.get("art", "daten")
        try:
            if art == "seite":
                roh = self.rfile.read(n)
                p, m, anz = seite_ablegen(roh, q.get("p") or None, q.get("m") or None)
                return self.senden(200, {"ok": True, "plattform": p, "modell": m, "bilder": anz})
            o = pfad(q.get("p"), q.get("m"))
            ziel_ordner = os.path.join(o, "Bilder" if art == "bilder" else "Daten")
            os.makedirs(ziel_ordner, exist_ok=True)
            ziel = os.path.join(ziel_ordner, sauber(q.get("name")))
            tmp = ziel + ".hochladen"
            rest = n
            with open(tmp, "wb") as f:
                while rest:
                    stueck = self.rfile.read(min(rest, 1024 * 1024))
                    if not stueck:
                        break
                    f.write(stueck)
                    rest -= len(stueck)
            if rest:
                os.remove(tmp)
                return self.senden(400, {"ok": False, "text": "Upload abgebrochen"})
            os.replace(tmp, ziel)
            return self.senden(200, {"ok": True})
        except ValueError as e:
            return self.senden(400, {"ok": False, "text": str(e)})

    def do_POST(self):
        u = urllib.parse.urlparse(self.path)
        if not self.erlaubt("POST", u.path):
            return
        BAUM_ZWISCHEN["veraltet"] = True
        try:
            b = self.json_body()
            if u.path == "/api/anmelden":
                ip = self.client_address[0]
                fenster = [t for t in VERSUCHE.get(ip, []) if t > time.time() - 600]
                if len(fenster) >= 8:
                    return self.senden(429, {"ok": False, "text": "Zu viele Versuche – bitte 10 Minuten warten."})
                pin = str(b.get("pin", "")).strip()
                e = json_lesen(EINST)
                if not e.get("pin"):
                    if not re.fullmatch(r"\d{4,8}", pin):
                        return self.senden(400, {"ok": False, "text": "Die PIN muss 4 bis 8 Ziffern haben."})
                    salz = secrets.token_hex(16)
                    e.update(pin=pin_hash(pin, salz), salz=salz)
                    json_schreiben(EINST, e)
                elif not hmac.compare_digest(pin_hash(pin, e["salz"]), e["pin"]):
                    VERSUCHE[ip] = fenster + [time.time()]
                    return self.senden(403, {"ok": False, "text": "PIN falsch"})
                VERSUCHE.pop(ip, None)
                t = sitzung_neu()
                return self.senden(200, {"ok": True}, kopf={"Set-Cookie": f"mb_sitzung={t}; Path=/; Max-Age={180 * 86400}; HttpOnly; SameSite=Lax"})
            if u.path == "/api/abmelden":
                s_ = json_lesen(SITZ)
                s_.pop(hashlib.sha256(self.sitzung().encode()).hexdigest(), None)
                json_schreiben(SITZ, s_)
                return self.senden(200, {"ok": True}, kopf={"Set-Cookie": "mb_sitzung=; Path=/; Max-Age=0"})
            if u.path == "/api/pin_aendern":
                e = json_lesen(EINST)
                if not hmac.compare_digest(pin_hash(str(b.get("alt", "")), e["salz"]), e["pin"]):
                    return self.senden(403, {"ok": False, "text": "Alte PIN falsch"})
                neu = str(b.get("neu", "")).strip()
                if not re.fullmatch(r"\d{4,8}", neu):
                    return self.senden(400, {"ok": False, "text": "Die PIN muss 4 bis 8 Ziffern haben."})
                salz = secrets.token_hex(16)
                e.update(pin=pin_hash(neu, salz), salz=salz)
                json_schreiben(EINST, e)
                return self.senden(200, {"ok": True})
            if u.path == "/api/notiz":
                o = pfad(b.get("p"), b.get("m"))
                if not os.path.isdir(o):
                    return self.senden(404, {"ok": False})
                status = b.get("status") if b.get("status") in ("", "will", "gedruckt") else ""
                info_setzen(o, status=status, bewertung=max(0, min(5, int(b.get("bewertung") or 0))),
                            notiz=str(b.get("notiz", ""))[:5000], filament=str(b.get("filament", ""))[:200])
                return self.senden(200, {"ok": True})
            if u.path == "/api/update_laden":
                o = pfad(b.get("p"), b.get("m"))
                if not os.path.isdir(o) or not info_lesen(o).get("url"):
                    return self.senden(404, {"ok": False, "text": "Modell ohne Link"})
                aid = uuid.uuid4().hex[:10]
                AUFTRAEGE[aid] = {"id": aid, "status": "läuft", "schritt": "Startet …", "zeit": int(time.time())}
                threading.Thread(target=update_auftrag, args=(aid, b.get("p"), b.get("m")), daemon=True).start()
                return self.senden(200, AUFTRAEGE[aid])
            if u.path == "/api/katalog":
                ziel = {"3dsets": katalog_3dsets, "cults": katalog_cults}.get(b.get("plattform"))
                if not ziel:
                    return self.senden(400, {"ok": False, "text": "Unbekannte Plattform"})
                aid = uuid.uuid4().hex[:10]
                AUFTRAEGE[aid] = {"id": aid, "status": "läuft", "schritt": "Startet …", "zeit": int(time.time())}
                threading.Thread(target=ziel, args=(aid,), daemon=True).start()
                return self.senden(200, AUFTRAEGE[aid])
            if u.path == "/api/nas_scan":
                aid = uuid.uuid4().hex[:10]
                AUFTRAEGE[aid] = {"id": aid, "status": "läuft", "schritt": "Startet …", "zeit": int(time.time())}

                def lauf(aid=aid):
                    try:
                        nas_scan(aid)
                    except Exception as e:
                        AUFTRAEGE[aid].update(status="fehler", schritt=str(e))
                threading.Thread(target=lauf, daemon=True).start()
                return self.senden(200, AUFTRAEGE[aid])
            if u.path == "/api/aenderungen_weg":
                o = pfad(b.get("p"), b.get("m"))
                if os.path.isdir(o):
                    info_setzen(o, aenderungen=None)
                return self.senden(200, {"ok": True})
            if u.path == "/api/updates":
                return self.senden(200, {"ok": True, "neu": updates_pruefen()})
            if u.path == "/api/import":
                url = str(b.get("url", "")).strip()
                if not re.match(r"^https?://", url):
                    return self.senden(400, {"ok": False, "text": "Bitte einen Link mit https:// einfügen"})
                aid = uuid.uuid4().hex[:10]
                AUFTRAEGE[aid] = {"id": aid, "url": url, "status": "läuft", "schritt": "Startet …", "zeit": int(time.time())}
                ziel = (b.get("p"), b.get("m")) if b.get("p") and b.get("m") else (None, None)
                threading.Thread(target=importieren, args=(aid, url) + ziel, daemon=True).start()
                return self.senden(200, AUFTRAEGE[aid])
            if u.path == "/api/konten":
                if b.get("trennen"):
                    k = konten_lesen()
                    k.pop(b.get("plattform", ""), None)
                    konten_schreiben(k)
                    return self.senden(200, konten_status())
                if b.get("plattform") == "cults":
                    z = {"user": str(b.get("user") or "").strip(), "key": str(b.get("key") or "").strip()}
                    nick = cults_abfrage("{myself{user{nick}}}", z)["myself"]["user"]["nick"]
                    k = konten_lesen()
                    k["cults"] = dict(z, name=nick, geprueft=time.strftime("%d.%m.%Y %H:%M"))
                    konten_schreiben(k)
                    return self.senden(200, dict(konten_status(), ok=True, name=nick))
                if b.get("plattform") != "makerworld":
                    return self.senden(400, {"ok": False, "text": "Diese Plattform folgt noch."})
                if b.get("email"):
                    schritt, text = mw_anmelden(b.get("email"), b.get("passwort"), b.get("code"))
                    if schritt != "fertig":
                        return self.senden(200, dict(konten_status(), ok=True, weiter=schritt, text=text))
                    return self.senden(200, dict(konten_status(), ok=True, name=text))
                name = mw_verbinden(b.get("token"))
                return self.senden(200, dict(konten_status(), ok=True, name=name))
            if u.path == "/api/profil_laden":
                pfad(b.get("p"), b.get("m"))
                aid = uuid.uuid4().hex[:10]
                AUFTRAEGE[aid] = {"id": aid, "status": "läuft", "schritt": "Startet …", "zeit": int(time.time())}
                threading.Thread(target=profil_auftrag, args=(aid, b.get("p"), b.get("m"), b.get("id")), daemon=True).start()
                return self.senden(200, AUFTRAEGE[aid])
            if u.path == "/api/stl":
                pfad(b.get("p"), b.get("m"))
                aid = uuid.uuid4().hex[:10]
                AUFTRAEGE[aid] = {"id": aid, "status": "läuft", "schritt": "Startet …", "zeit": int(time.time())}
                threading.Thread(target=stl_auftrag, args=(aid, b.get("p"), b.get("m"), b.get("datei")), daemon=True).start()
                return self.senden(200, AUFTRAEGE[aid])
            if u.path == "/api/neu":
                o = pfad(b.get("p"), b.get("m"))
                os.makedirs(os.path.join(o, "Daten"), exist_ok=True)
                os.makedirs(os.path.join(o, "Bilder"), exist_ok=True)
                if b.get("url"):
                    info_schreiben(o, url=b["url"])
                return self.senden(200, {"ok": True, "plattform": sauber(b.get("p")), "modell": sauber(b.get("m"))})
            if u.path == "/api/loeschen":
                o = pfad(b.get("p"), b.get("m"))
                papierkorb = os.path.join(DATEN, ".papierkorb", time.strftime("%Y%m%d-%H%M%S"))
                os.makedirs(papierkorb, exist_ok=True)
                if b.get("datei"):
                    unter = "Bilder" if b.get("art") == "bilder" else "Daten"
                    f = os.path.join(o, unter, sauber(b["datei"]))
                    if os.path.isfile(f):
                        shutil.move(f, os.path.join(papierkorb, os.path.basename(f)))
                elif os.path.isdir(o):
                    shutil.move(o, os.path.join(papierkorb, os.path.basename(o)))
                    try:
                        os.rmdir(os.path.dirname(o))
                    except OSError:
                        pass
                return self.senden(200, {"ok": True})
            if u.path == "/api/umbenennen":
                alt = pfad(b.get("p"), b.get("m"))
                neu = pfad(b.get("np") or b.get("p"), b.get("nm") or b.get("m"))
                if os.path.exists(neu):
                    return self.senden(409, {"ok": False, "text": "Diesen Namen gibt es schon"})
                os.makedirs(os.path.dirname(neu), exist_ok=True)
                shutil.move(alt, neu)
                try:
                    os.rmdir(os.path.dirname(alt))
                except OSError:
                    pass
                return self.senden(200, {"ok": True, "plattform": os.path.basename(os.path.dirname(neu)), "modell": os.path.basename(neu)})
        except ValueError as e:
            return self.senden(400, {"ok": False, "text": str(e)})
        self.senden(404, {"ok": False})


if __name__ == "__main__":
    os.makedirs(DATEN, exist_ok=True)
    shutil.rmtree(os.path.join(DATEN, ".tmp"), ignore_errors=True)
    os.makedirs(os.path.join(DATEN, ".tmp"), exist_ok=True)
    threading.Thread(target=update_schleife, daemon=True).start()
    threading.Thread(target=baum_frisch_halten, daemon=True).start()
    print(f"ModelBrowser läuft auf Port {PORT}, Ablage {DATEN}", flush=True)
    StillerServer(("0.0.0.0", PORT), H).serve_forever()
