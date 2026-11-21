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
    i = info_lesen(ordner)
    i.update({k: v for k, v in werte.items() if v})
    with open(os.path.join(ordner, "info.json"), "w", encoding="utf-8") as f:
        json.dump(i, f, ensure_ascii=False, indent=1)


def info_setzen(ordner, **werte):
    """Wie info_schreiben, aber leere Werte zählen auch (None entfernt den Schlüssel)."""
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


def baum():
    erg = []
    os.makedirs(DATEN, exist_ok=True)
    for p in sorted(os.listdir(DATEN), key=str.lower):
        pp = os.path.join(DATEN, p)
        if not os.path.isdir(pp) or p.startswith("."):
            continue
        modelle = []
        for m in sorted(os.listdir(pp), key=str.lower):
            mp = os.path.join(pp, m)
            if not os.path.isdir(mp) or m.startswith("."):
                continue
            bilder = dateien(os.path.join(mp, "Bilder"))
            i = info_lesen(mp)
            eigene = [b for b in bilder if b["name"].startswith("eigen_")]
            titelbild = (eigene[0] if i.get("status") == "gedruckt" and eigene else (bilder[0] if bilder else {})).get("name", "")
            modelle.append({"name": m, "bilder": len(bilder), "dateien": len(dateien(os.path.join(mp, "Daten"))),
                            "titelbild": titelbild, "seite": os.path.exists(os.path.join(mp, "seite.html")),
                            "zeit": int(os.path.getmtime(mp)), "url": i.get("url", ""), "status": i.get("status", ""),
                            "bewertung": i.get("bewertung", 0), "update": bool(i.get("update")), "such": suchtext(i)})
        erg.append({"name": p, "modelle": modelle})
    return erg


def modell(p, m):
    o = pfad(p, m)
    if not os.path.isdir(o):
        return None
    return {"plattform": sauber(p), "name": sauber(m), "info": info_lesen(o),
            "seite": os.path.exists(os.path.join(o, "seite.html")),
            "bilder": dateien(os.path.join(o, "Bilder")), "dateien": dateien(os.path.join(o, "Daten"))}


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
    return d


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
                   profile=d["profile"], tags=d["tags"], gespeichert=time.strftime("%Y-%m-%d %H:%M"), stand=d["stand"])
    info_setzen(o, update=None)
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
        a["schritt"] = "Bilder werden geladen …"
        p, m, n = seite_ablegen(roh, p, m, url=url)
        text = f"Gespeichert mit {n} Bildern"
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
            "printables": {"bald": True}, "cults": {"bald": True}}


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
         ("POST", "/api/anmelden"), ("POST", "/api/import")}


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
            stand = str(d.get("updateTime") or "")
            if not stand:
                continue
            if not i.get("stand"):
                info_setzen(o, stand=stand)
            elif stand != i.get("stand") and not i.get("update"):
                info_setzen(o, update=True)
                neu += 1
            time.sleep(2)
    return neu


def update_schleife():
    time.sleep(120)
    while True:
        try:
            n = updates_pruefen()
            print(f"Update-Prüfung fertig, {n} neue Updates", flush=True)
        except Exception as e:
            print("Update-Prüfung:", e, flush=True)
        time.sleep(24 * 3600)


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
    print(f"ModelBrowser läuft auf Port {PORT}, Ablage {DATEN}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), H).serve_forever()
