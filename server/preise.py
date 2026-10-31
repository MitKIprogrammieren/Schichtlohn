"""Preisvergleich: aktuelle Angebote von eBay und AliExpress für die Sorten im Lager.

Zugangsdaten trägt der Nutzer in der App ein (Einstellungen → Preisvergleich):
  eBay        Client-ID und Client-Secret einer App aus developer.ebay.com (Browse API, Marktplatz EBAY_DE)
  AliExpress  App-Key, App-Secret und Tracking-ID aus dem Partnerprogramm (portals.aliexpress.com)

eBay sucht zuerst per EAN (GTIN), sonst über Marke + Material + Farbe; AliExpress immer über diese Wörter.
Treffer zählen nur, wenn Marke und Farbe im Titel stehen – lieber kein Preis als ein falscher.
"""
import base64
import hashlib
import hmac
import json
import re
import time
import urllib.parse
import urllib.request

UA = "SchichtLohn-Server"
_letzte = {"treffer": 0}  # passende Angebote der letzten Suche – fürs Protokoll
_ebay_token = {"wert": "", "bis": 0, "fuer": ""}

FARBE_DE_EN = {"schwarz": "black", "weiß": "white", "weiss": "white", "grau": "grey", "rot": "red", "blau": "blue", "grün": "green",
               "gelb": "yellow", "orange": "orange", "lila": "purple", "violett": "purple", "rosa": "pink", "pink": "pink",
               "braun": "brown", "beige": "beige", "silber": "silver", "gold": "gold", "transparent": "transparent", "natur": "natural"}


def _anfrage(url, daten=None, kopf=None, timeout=25):
    req = urllib.request.Request(url, data=daten, headers=dict({"User-Agent": UA}, **(kopf or {})))
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8") or "{}")


def _norm(s):
    return re.sub(r"[^a-z0-9äöüß]+", " ", str(s or "").lower().replace("grey", "gray")).strip()


def _passt(titel, e):
    """Marke und (mindestens ein Wort der) Farbe müssen im Titel stehen, das Material auch."""
    t = " " + _norm(titel).replace("gray", "gray grey") + " "
    marke = _norm(e.get("hersteller")).split()
    if marke and not all(w in t for w in marke[:2]):
        return False
    mat = _norm(e.get("material")).split()
    if mat and mat[0] not in t.replace(" ", " "):
        return False
    farbe = [w for w in _norm(e.get("farbe")).split() if len(w) > 2]
    farbe += [FARBE_DE_EN[w] for w in farbe if w in FARBE_DE_EN]
    return not farbe or any(f" {w} " in t or w in t for w in farbe)


def gewicht_aus_titel(titel):
    """Spulengewicht in Gramm aus dem Angebotstitel („1kg“, „1,75mm 1000g“, „250 g“) – None, wenn nichts dasteht."""
    t = str(titel or "").lower().replace(",", ".")
    m = re.search(r"(\d+(?:\.\d+)?)\s*kg\b", t)
    if m:
        g = float(m.group(1)) * 1000
    else:
        m = re.search(r"\b(\d{3,4})\s*g(?:r|ramm)?\b", t)
        g = float(m.group(1)) if m else 0
    return int(g) if 100 <= g <= 10000 else None


def mehrfach(titel):
    """Mehrfachpack („2x“, „3 Rollen“, „4er Pack“, „Bundle“) → Anzahl, sonst 1."""
    t = str(titel or "").lower()
    m = re.search(r"\b(\d{1,2})\s*(?:x|stück|stk|rollen|spulen|pack|er pack|er-pack|rolls|spools)\b", t)
    if m and 1 < int(m.group(1)) <= 20:
        return int(m.group(1))
    return 1


def _je_kg(preis, titel, e):
    """Preis je kg; Gewicht aus dem Titel, sonst wie die Spule im Lager. Mehrfachpacks werden geteilt."""
    gew = gewicht_aus_titel(titel) or int(e.get("gewicht") or 1000)
    n = mehrfach(titel)
    return round(preis / n / (gew / 1000), 2), gew, n


def suchtext(e):
    bes = [b for b in (e.get("besonderheiten") or []) if str(b).lower() not in ("basic",)]
    return " ".join(str(x) for x in [e.get("hersteller"), e.get("material"), *bes, e.get("farbe"), "filament"] if x)


# ---------------------------------------------------------------- eBay (Browse API)

def ebay_token(cid, sec):
    if _ebay_token["wert"] and _ebay_token["fuer"] == cid and time.time() < _ebay_token["bis"] - 60:
        return _ebay_token["wert"]
    auth = base64.b64encode(f"{cid}:{sec}".encode()).decode()
    d = _anfrage("https://api.ebay.com/identity/v1/oauth2/token",
                 urllib.parse.urlencode({"grant_type": "client_credentials", "scope": "https://api.ebay.com/oauth/api_scope"}).encode(),
                 {"Authorization": "Basic " + auth, "Content-Type": "application/x-www-form-urlencoded"})
    if not d.get("access_token"):
        raise RuntimeError("eBay: kein Zugang – Client-ID und Secret prüfen")
    _ebay_token.update(wert=d["access_token"], bis=time.time() + int(d.get("expires_in") or 7200), fuer=cid)
    return d["access_token"]


def _ebay_suche(token, params):
    q = urllib.parse.urlencode(dict(params, limit=20, filter="buyingOptions:{FIXED_PRICE},conditions:{NEW},deliveryCountry:DE"))
    d = _anfrage("https://api.ebay.com/buy/browse/v1/item_summary/search?" + q, None,
                 {"Authorization": "Bearer " + token, "X-EBAY-C-MARKETPLACE-ID": "EBAY_DE",
                  "X-EBAY-C-ENDUSERCTX": "contextualLocation=country=DE"})
    return d.get("itemSummaries") or []


def ebay_angebot(cfg, e):
    token = ebay_token(cfg["id"], cfg["secret"])
    treffer, per_ean = [], False
    codes = [c for c in (e.get("codes") or []) if re.fullmatch(r"\d{8,14}", str(c))]
    for c in codes[:2]:
        treffer = _ebay_suche(token, {"gtin": c})
        if treffer:
            per_ean = True
            break
    if not treffer:
        treffer = [t for t in _ebay_suche(token, {"q": suchtext(e)}) if _passt(t.get("title"), e)]
    beste = None
    _letzte["treffer"] = len(treffer)
    for t in treffer:
        p = t.get("price") or {}
        if p.get("currency") != "EUR":
            continue
        versand = 0.0
        for v in t.get("shippingOptions") or []:
            k = (v.get("shippingCost") or {})
            if k.get("currency") == "EUR":
                versand = float(k.get("value") or 0)
                break
        summe = float(p.get("value") or 0) + versand
        if summe <= 0:
            continue
        pk, gew, n = _je_kg(summe, t.get("title"), e)
        if not beste or pk < beste["pk"]:
            beste = {"preis": round(summe, 2), "versand": round(versand, 2), "pk": pk, "gew": gew, "stueck": n,
                     "titel": t.get("title") or "", "url": t.get("itemWebUrl") or "", "per_ean": per_ean}
    return beste


# ---------------------------------------------------------------- AliExpress (Partnerprogramm)

def _ali_signieren(params, secret):
    roh = "".join(f"{k}{params[k]}" for k in sorted(params))
    return hmac.new(secret.encode(), roh.encode(), hashlib.sha256).hexdigest().upper()


def ali_angebot(cfg, e):
    params = {"app_key": cfg["key"], "method": "aliexpress.affiliate.product.query", "sign_method": "sha256",
              "timestamp": str(int(time.time() * 1000)), "v": "2.0", "format": "json",
              "keywords": suchtext(e), "target_currency": "EUR", "target_language": "DE", "ship_to_country": "DE",
              "page_size": "20", "sort": "SALE_PRICE_ASC"}
    if cfg.get("tracking"):
        params["tracking_id"] = cfg["tracking"]
    params["sign"] = _ali_signieren(params, cfg["secret"])
    d = _anfrage("https://api-sg.aliexpress.com/sync?" + urllib.parse.urlencode(params))
    if d.get("error_response"):
        raise RuntimeError("AliExpress: " + str(d["error_response"].get("msg") or d["error_response"]))
    res = ((d.get("aliexpress_affiliate_product_query_response") or {}).get("resp_result") or {})
    prods = ((res.get("result") or {}).get("products") or {}).get("product") or []
    beste = None
    _letzte["treffer"] = sum(1 for p in prods if _passt(p.get("product_title"), e))
    for p in prods:
        if not _passt(p.get("product_title"), e):
            continue
        preis = float(p.get("target_sale_price") or p.get("sale_price") or 0)
        if preis <= 0:
            continue
        pk, gew, n = _je_kg(preis, p.get("product_title"), e)
        if not beste or pk < beste["pk"]:
            beste = {"preis": round(preis, 2), "versand": None, "pk": pk, "gew": gew, "stueck": n,
                     "titel": p.get("product_title") or "", "url": p.get("promotion_link") or p.get("product_detail_url") or ""}
    return beste


# ---------------------------------------------------------------- Ablauf

def abrufen(cfg, sorten, alt=None, melde=print):
    """sorten: [(uid, beschreibung)] → {uid: {"ebay": …, "ali": …, "zeit": …}}, dazu Statistik."""
    alt = alt or {}
    out, stat = {}, {"ebay": 0, "ali": 0, "fehler": [], "zeilen": []}
    eb = (cfg or {}).get("ebay") or {}
    al = (cfg or {}).get("ali") or {}
    eb_an = bool(eb.get("id") and eb.get("secret"))
    al_an = bool(al.get("key") and al.get("secret"))
    for uid, e in sorten:
        if not (e.get("hersteller") and e.get("material")):
            continue
        z = dict(alt.get(uid) or {})
        zeile = {"uid": uid, "sorte": " ".join(str(x) for x in [e.get("hersteller"), e.get("material"), *(e.get("besonderheiten") or []), "·", e.get("farbe")] if x)}
        for name, an, f in (("ebay", eb_an, lambda: ebay_angebot(eb, e)), ("ali", al_an, lambda: ali_angebot(al, e))):
            schluessel_da = bool((eb if name == "ebay" else al).get("secret"))
            if not an:
                z.pop(name, None)
                zeile[name] = {"s": "uebersprungen" if schluessel_da else "aus"}
                continue
            _letzte["treffer"] = 0
            try:
                a = f()
                if a:
                    z[name] = a
                    stat[name] += 1
                    zeile[name] = {"s": "ok", "preis": a["preis"], "pk": a.get("pk"), "treffer": _letzte["treffer"], "ean": bool(a.get("per_ean")),
                                   "titel": a.get("titel", "")[:120]}
                else:
                    z.pop(name, None)
                    zeile[name] = {"s": "keiner", "treffer": _letzte["treffer"]}
            except Exception as ex:  # Zugang falsch o. Ä.: einmal melden und diesen Händler für diesen Lauf aufgeben
                msg = str(getattr(ex, "reason", None) or ex)[:200]
                stat["fehler"].append(msg)
                zeile[name] = {"s": "fehler", "text": msg}
                if name == "ebay":
                    eb_an = False
                else:
                    al_an = False
            time.sleep(0.3)
        stat["zeilen"].append(zeile)
        z["zeit"] = time.strftime("%Y-%m-%d %H:%M")
        out[uid] = z
    return out, stat
