"""MCP-Anbindung des SchichtLohn-Servers (Model Context Protocol, „Streamable HTTP“ ohne Ereignisstrom).

Claude (claude.ai, Desktop, Code) spricht JSON-RPC per POST an /mcp/<schlüssel>. Werkzeuge: Lager suchen und lesen,
Sorten anlegen und ändern, Verbrauch buchen, Drucker, Druckprotokoll und Verbrauchsauswertung.
Löschen gibt es bewusst nicht – das bleibt in der App.

app.py setzt W (Zugriff auf Lager, Listen, Zustände) beim Start."""
import json
import re
import time

W = None  # wird von app.py gesetzt
PROTOKOLLE = ("2025-06-18", "2025-03-26", "2024-11-05")
NAME = "SchichtLohn"

# Felder einer Sorte, die über sorte_anlegen/sorte_aendern gesetzt werden dürfen (Name in der App → Bedeutung)
FELDER = {
    "hersteller": "Hersteller, z. B. „Bambu Lab“", "material": "Material, z. B. „PETG“", "farbe": "Farbname",
    "hex": "Farbe als #rrggbb", "besonderheiten": "Liste, z. B. [\"HF\"], [\"Matt\"], [\"CF\"]", "gewicht": "Nettogewicht einer Spule in g",
    "spulen": "Anzahl Spulen im Lager (angebrochene mitgezählt)", "reste": "Restgewichte angebrochener Spulen in g, Liste",
    "refills": "davon Refills ohne Spule", "ausfuehrung": "„spule“ oder „refill“", "durchmesser": "mm, meist 1.75",
    "preis": "Preis in € je kg", "duese_min": "°C", "duese_max": "°C", "bett_min": "°C", "bett_max": "°C",
    "trocknen_c": "Trocknen °C", "trocknen_h": "Trocknen Stunden", "flow": "Flussrate, z. B. 0.95", "mvs": "max. Volumenstrom mm³/s",
    "kammer": "Kammertemperatur °C", "schwund": "Schwund in %", "td": "TD-Wert (HueForge)", "k": "Pressure Advance",
    "bambu_id": "Filament-ID aus Bambu Studio (z. B. GFG02 oder P…)", "codes": "EAN-Codes, Liste", "fcode": "Herstellercode",
    "sku": "Artikelnummer", "ams_farben": "gelernte AMS-Farben, Liste #rrggbb", "notiz": "freie Notiz",
}
ZAHLEN = {"gewicht", "spulen", "refills", "durchmesser", "preis", "duese_min", "duese_max", "bett_min", "bett_max", "trocknen_c",
          "trocknen_h", "flow", "mvs", "kammer", "schwund", "td", "k"}
LISTEN = {"besonderheiten", "reste", "codes", "ams_farben"}


class McpFehler(Exception):
    def __init__(self, code, text):
        super().__init__(text)
        self.code = code


# ---------------------------------------------------------------- Hilfen

def _sorten():
    out = []
    for it in W.liste_lesen(W.ENT):
        d = W._desc(it)
        if d.get("typ"):
            continue
        out.append((it, d))
    return out


def _bestand(d):
    gw = W._zahl(d.get("gewicht"), 1000) or 1000
    sp = int(W._zahl(d.get("spulen"), 1))
    if sp <= 0:
        return 0
    rs = [W._zahl(r) for r in (d.get("reste") or []) if W._zahl(r) > 0][:sp]
    return int(round((sp - len(rs)) * gw + sum(rs)))


def _name(d):
    teile = [d.get("hersteller"), d.get("material")] + list(d.get("besonderheiten") or [])
    n = " ".join(str(x) for x in teile if x)
    return n + (" · " + d["farbe"] if d.get("farbe") else "")


def _kurz(it, d):
    x = {"uid": it["uid"], "name": it.get("summary") or _name(d), "hersteller": d.get("hersteller") or "", "material": d.get("material") or "",
         "farbe": d.get("farbe") or "", "hex": d.get("hex") or "", "besonderheiten": d.get("besonderheiten") or [],
         "spulen": int(W._zahl(d.get("spulen"), 1)), "bestand_g": _bestand(d), "gewicht_g": int(W._zahl(d.get("gewicht"), 1000) or 1000)}
    if d.get("preis") not in (None, ""):
        x["preis_eur_kg"] = d.get("preis")
    if d.get("duese_min") or d.get("duese_max"):
        x["duese_c"] = f"{d.get('duese_min') or '?'}–{d.get('duese_max') or '?'}"
    if d.get("bett_min") or d.get("bett_max"):
        x["bett_c"] = f"{d.get('bett_min') or '?'}–{d.get('bett_max') or '?'}"
    return x


def _finde(uid):
    for it, d in _sorten():
        if it["uid"] == uid:
            return it, d
    raise McpFehler(-32602, f"Keine Sorte mit uid {uid} – erst lager_suchen aufrufen")


def _pruefen(felder):
    if not isinstance(felder, dict):
        raise McpFehler(-32602, "felder muss ein Objekt sein")
    out = {}
    for k, v in felder.items():
        if k not in FELDER:
            raise McpFehler(-32602, f"Unbekanntes Feld „{k}“. Erlaubt: {', '.join(FELDER)}")
        if v is None or v == "":
            out[k] = None
            continue
        if k in ZAHLEN:
            try:
                v = float(str(v).replace(",", "."))
            except ValueError:
                raise McpFehler(-32602, f"„{k}“ muss eine Zahl sein")
            v = int(v) if k in ("spulen", "refills", "gewicht") or v.is_integer() and k not in ("flow", "k", "durchmesser", "schwund", "preis") else v
        elif k in LISTEN:
            if not isinstance(v, list):
                v = [x.strip() for x in str(v).split(",") if x.strip()]
            if k == "reste":
                v = [int(round(float(x))) for x in v]
        elif k == "hex":
            v = str(v).strip().lower()
            v = v if v.startswith("#") else "#" + v
            if not re.fullmatch(r"#[0-9a-f]{6}", v):
                raise McpFehler(-32602, "hex muss die Form #rrggbb haben")
        elif k == "ausfuehrung" and v not in ("spule", "refill"):
            raise McpFehler(-32602, "ausfuehrung ist „spule“ oder „refill“")
        else:
            v = str(v).strip()
        out[k] = v
    return out


def _zeit(t):
    try:
        return time.mktime(time.strptime(str(t)[:19], "%Y-%m-%dT%H:%M:%S"))
    except (ValueError, TypeError):
        return 0


# ---------------------------------------------------------------- Werkzeuge

def lager_suchen(a):
    q = str(a.get("suche") or "").lower().split()
    mat = str(a.get("material") or "").lower()
    her = str(a.get("hersteller") or "").lower()
    nur = a.get("nur_bestand", True) is not False
    out = []
    for it, d in _sorten():
        x = _kurz(it, d)
        if nur and x["spulen"] <= 0:
            continue
        text = " ".join([x["name"], x["farbe"], " ".join(x["besonderheiten"]), d.get("bambu_id") or "", " ".join(d.get("codes") or [])]).lower()
        if q and not all(w in text for w in q):
            continue
        if mat and mat not in x["material"].lower():
            continue
        if her and her not in x["hersteller"].lower():
            continue
        out.append(x)
    out.sort(key=lambda x: x["name"].lower())
    gr = int(a.get("limit") or 100)
    return {"anzahl": len(out), "sorten": out[:gr], "gekuerzt": len(out) > gr,
            "summe_g": sum(x["bestand_g"] for x in out)}


def sorte_lesen(a):
    it, d = _finde(str(a.get("uid") or ""))
    return {"uid": it["uid"], "name": it.get("summary"), "bestand_g": _bestand(d), "daten": d}


def sorte_anlegen(a):
    f = _pruefen(a.get("felder") or {k: v for k, v in a.items() if k in FELDER})
    if not f.get("hersteller") or not f.get("material"):
        raise McpFehler(-32602, "hersteller und material sind Pflicht")
    d = {"v": 2, "hersteller": "", "material": "", "farbe": "", "hex": "#888888", "besonderheiten": [], "gewicht": 1000, "spulen": 1,
         "refills": 0, "reste": [], "codes": [], "codes_refill": [], "durchmesser": 1.75, "ausfuehrung": "spule", "ams_farben": []}
    d.update({k: v for k, v in f.items() if v is not None})
    d["quelle_anlage"] = "Claude (MCP)"
    r = W.liste_aendern(W.ENT, "add_item", {"item": _name(d), "description": json.dumps(d, ensure_ascii=False)})
    return {"ok": True, "uid": r.get("uid"), "name": _name(d), "bestand_g": _bestand(d)}


def sorte_aendern(a):
    it, d = _finde(str(a.get("uid") or ""))
    f = _pruefen(a.get("felder") or {})
    if not f:
        raise McpFehler(-32602, "felder ist leer – was soll geändert werden?")
    vorher = {k: d.get(k) for k in f}
    neu = dict(d)
    for k, v in f.items():
        if v is None:
            neu.pop(k, None)
        else:
            neu[k] = v
    # selbst gesetzte Werte sind keine Standardwerte mehr
    if isinstance(neu.get("werte_standard"), list):
        neu["werte_standard"] = [x for x in neu["werte_standard"] if x not in f]
    name = _name(neu) if any(k in f for k in ("hersteller", "material", "farbe", "besonderheiten")) else None
    W.liste_aendern(W.ENT, "update_item", {"item": it["uid"], "description": json.dumps(neu, ensure_ascii=False), "rename": name})
    return {"ok": True, "uid": it["uid"], "name": name or it.get("summary"), "vorher": vorher, "nachher": {k: neu.get(k) for k in f},
            "bestand_g": _bestand(neu)}


def verbrauch_buchen(a):
    it, d = _finde(str(a.get("uid") or ""))
    try:
        g = float(str(a.get("gramm")).replace(",", "."))
    except (TypeError, ValueError):
        raise McpFehler(-32602, "gramm muss eine Zahl sein")
    if not 0 < g <= 20000:
        raise McpFehler(-32602, "gramm muss zwischen 0 und 20000 liegen")
    vorher = _bestand(d)
    neu, bestand = W.abbuchen_rechnen(d, g)
    W.liste_aendern(W.ENT, "update_item", {"item": it["uid"], "description": json.dumps(neu, ensure_ascii=False)})
    preis = W._zahl(d.get("preis"))
    log = {"typ": "verbrauch", "v": 1, "zeit": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "drucker": str(a.get("drucker") or ""), "ort": "",
           "sorte": it.get("summary"), "uid": it["uid"], "hersteller": d.get("hersteller") or "", "material": d.get("material") or "",
           "hex": d.get("hex") or "", "gramm": round(g, 1), "preis": preis or None,
           "kosten": round(g / 1000 * preis, 2) if preis else None,
           "anlass": str(a.get("anlass") or "Von Claude gebucht"), "quelle": "Claude (MCP)"}
    W.liste_aendern(W.META, "add_item", {"item": f"{time.strftime('%d.%m.%Y %H:%M')} · {log['drucker'] or 'manuell'} · {W._gram(g)} g · {it.get('summary')}",
                                         "description": json.dumps(log, ensure_ascii=False)})
    return {"ok": True, "uid": it["uid"], "name": it.get("summary"), "abgebucht_g": round(g, 1), "vorher_g": vorher, "bestand_g": int(round(bestand))}


def drucker_status(a):
    z = {x["entity_id"]: x for x in W.zustaende_liste()}
    out = []
    for eid, x in z.items():
        m = re.match(r"^sensor\.(.+)_druckstatus$", eid)
        if not m:
            continue
        pre = m.group(1)
        v = lambda k: (z.get(f"sensor.{pre}_{k}") or {}).get("state")
        dr = {"drucker": (x.get("attributes") or {}).get("drucker_name") or pre.split("_")[0].upper(), "status": x.get("state"),
              "fortschritt_prozent": v("druckfortschritt"), "restzeit_min": v("verbleibende_zeit"), "aufgabe": v("aktuelle_aufgabe") or ""}
        faecher = []
        for e2, y in sorted(z.items()):
            n = re.match(r"^sensor\." + re.escape(pre) + r"_(?:ams_(\d+)_slot_(\d+)|externalspool(\d*)_externe_spule)$", e2)
            if not n:
                continue
            at = y.get("attributes") or {}
            if at.get("empty"):
                ort, inhalt = None, "leer"
            else:
                inhalt = " ".join(str(s) for s in (at.get("name") or at.get("type") or y.get("state"), str(at.get("color") or "")[:7]) if s)
            ams = int(n.group(1)) if n.group(1) else 0
            ort = "Extern" if not n.group(1) else (f"AMS HT {ams - 127}" if ams >= 128 else f"AMS {ams} Fach {n.group(2)}")
            f = {"ort": ort, "inhalt": inhalt}
            if at.get("remain") not in (None, -1) and not at.get("empty"):
                f["rest_prozent"] = at.get("remain")
            if at.get("active"):
                f["aktiv"] = True
            faecher.append(f)
        dr["faecher"] = faecher
        out.append(dr)
    return {"drucker": sorted(out, key=lambda d: d["drucker"])}


def drucke_auflisten(a):
    l, _ = W.daten_lesen(W.DRUCKE_KEY)
    l = l if isinstance(l, list) else []
    tage = float(a.get("tage") or 30)
    grenze = time.time() - tage * 86400 if tage > 0 else 0
    dr = str(a.get("drucker") or "").lower()
    q = str(a.get("suche") or "").lower()
    out = []
    for x in l:
        if not isinstance(x, dict):
            continue
        t = _zeit(x.get("ende") or x.get("start"))
        if grenze and t and t < grenze:
            continue
        if dr and dr not in str(x.get("drucker") or "").lower():
            continue
        if q and q not in str(x.get("titel") or "").lower():
            continue
        out.append({"titel": x.get("titel"), "drucker": x.get("drucker"), "ende": x.get("ende"), "minuten": x.get("minuten"),
                    "gramm": x.get("gramm"), "abgebrochen": bool(x.get("abgebrochen")), "herkunft": x.get("herkunft") or "server",
                    "filamente": [{"g": f.get("gramm"), "typ": f.get("typ"), "farbe": f.get("farbe"), "name": f.get("name")} for f in x.get("filamente") or []]})
    gr = int(a.get("limit") or 50)
    return {"anzahl": len(out), "summe_g": round(sum(float(x.get("gramm") or 0) for x in out), 1), "drucke": out[:gr], "gekuerzt": len(out) > gr}


def verbrauch_auswerten(a):
    von, bis = str(a.get("von") or ""), str(a.get("bis") or "")
    nach = str(a.get("gruppe") or "material")
    if nach not in ("material", "drucker", "sorte", "monat", "hersteller"):
        raise McpFehler(-32602, "gruppe: material, drucker, sorte, hersteller oder monat")
    gr = {}
    n = 0
    for it in W.liste_lesen(W.META):
        d = W._desc(it)
        if d.get("typ") != "verbrauch":
            continue
        z = str(d.get("zeit") or "")[:10]
        if (von and z < von) or (bis and z > bis):
            continue
        k = z[:7] if nach == "monat" else (d.get(nach) or "unbekannt")
        g = gr.setdefault(k, {"gruppe": k, "gramm": 0.0, "kosten_eur": 0.0, "buchungen": 0})
        g["gramm"] += float(d.get("gramm") or 0)
        g["kosten_eur"] += float(d.get("kosten") or 0)
        g["buchungen"] += 1
        n += 1
    l = sorted(gr.values(), key=lambda x: (x["gruppe"] if nach == "monat" else -x["gramm"]))
    for x in l:
        x["gramm"], x["kosten_eur"] = round(x["gramm"], 1), round(x["kosten_eur"], 2)
    return {"buchungen": n, "summe_g": round(sum(x["gramm"] for x in l), 1), "summe_eur": round(sum(x["kosten_eur"] for x in l), 2),
            "gruppen": l, "hinweis": "Nur im Lager abgebuchter Verbrauch; Kosten nur, wo die Sorte einen Preis hat."}


def nicht_zugeordnet(a):
    out = []
    for it in W.liste_lesen(W.ENT):
        d = W._desc(it)
        if d.get("typ") == "offen":
            out.append({"uid": it["uid"], "gramm": d.get("gramm"), "drucker": d.get("drucker"), "ort": d.get("ort"), "material": d.get("material"),
                        "farbe": d.get("farbe"), "filament_id": d.get("fid"), "grund": d.get("grund"), "zeit": d.get("zeit")})
    return {"anzahl": len(out), "offen": out}


S_TEXT = {"type": "string"}
WERKZEUGE = [
    ("lager_suchen", "Sorten im Filamentlager suchen (Name, Farbe, Material, Hersteller, EAN, Bambu-ID). Liefert uid, Bestand in g, Spulen, Preis, Temperaturen.",
     {"suche": dict(S_TEXT, description="Suchwörter, alle müssen vorkommen, z. B. „petg schwarz“"), "material": S_TEXT, "hersteller": S_TEXT,
      "nur_bestand": {"type": "boolean", "description": "nur Sorten mit Bestand (Standard: ja)"}, "limit": {"type": "integer"}}, [], True, lager_suchen),
    ("sorte_lesen", "Alle gespeicherten Daten einer Sorte (Druckwerte, Preis, Kauf, Codes).", {"uid": S_TEXT}, ["uid"], True, sorte_lesen),
    ("sorte_anlegen", "Neue Sorte im Lager anlegen. Pflicht: hersteller, material. Felder: " + ", ".join(f"{k} ({v})" for k, v in FELDER.items()),
     {"felder": {"type": "object", "description": "Felder der Sorte"}}, ["felder"], False, sorte_anlegen),
    ("sorte_aendern", "Felder einer Sorte ändern (z. B. Druckwerte, Preis, Spulenzahl, Reste, Name-Teile). null löscht ein Feld. Erlaubte Felder: " + ", ".join(FELDER),
     {"uid": S_TEXT, "felder": {"type": "object"}}, ["uid", "felder"], False, sorte_aendern),
    ("verbrauch_buchen", "Verbrauchtes Filament von einer Sorte abbuchen und in der Verbrauchsliste vermerken (wie nach einem Druck).",
     {"uid": S_TEXT, "gramm": {"type": "number"}, "drucker": S_TEXT, "anlass": dict(S_TEXT, description="z. B. „Fehldruck“, „Korrektur“")},
     ["uid", "gramm"], False, verbrauch_buchen),
    ("drucker_status", "Alle Drucker: Status, Fortschritt, Restzeit, Aufgabe und Belegung der AMS-Fächer.", {}, [], True, drucker_status),
    ("drucke_auflisten", "Druckprotokoll: fertige und abgebrochene Drucke mit Gewicht je Filament.",
     {"tage": {"type": "number", "description": "Zeitraum zurück in Tagen (0 = alle, Standard 30)"}, "drucker": S_TEXT, "suche": S_TEXT, "limit": {"type": "integer"}},
     [], True, drucke_auflisten),
    ("verbrauch_auswerten", "Abgebuchten Verbrauch und Kosten zusammenzählen, gruppiert nach material, drucker, sorte, hersteller oder monat.",
     {"von": dict(S_TEXT, description="JJJJ-MM-TT"), "bis": dict(S_TEXT, description="JJJJ-MM-TT"), "gruppe": {"type": "string", "enum": ["material", "drucker", "sorte", "hersteller", "monat"]}},
     [], True, verbrauch_auswerten),
    ("nicht_zugeordnet", "Verbrauch, der keiner Sorte zugeordnet werden konnte (in der App unter „Nicht zugeordnet“).", {}, [], True, nicht_zugeordnet),
]
NACH_NAME = {w[0]: w for w in WERKZEUGE}


def _liste():
    return [{"name": n, "description": b, "inputSchema": {"type": "object", "properties": p, "required": r},
             "annotations": {"readOnlyHint": lesen, "destructiveHint": False}} for n, b, p, r, lesen, _ in WERKZEUGE]


def bearbeiten(nachricht, version=""):
    """Eine JSON-RPC-Nachricht → Antwort (dict) oder None bei Benachrichtigungen."""
    if not isinstance(nachricht, dict) or nachricht.get("jsonrpc") != "2.0":
        return {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Ungültige Anfrage"}}
    mid, methode, p = nachricht.get("id"), nachricht.get("method"), nachricht.get("params") or {}
    if mid is None:
        return None
    try:
        if methode == "initialize":
            v = p.get("protocolVersion")
            erg = {"protocolVersion": v if v in PROTOKOLLE else PROTOKOLLE[0], "capabilities": {"tools": {"listChanged": False}},
                   "serverInfo": {"name": NAME, "title": "SchichtLohn – Filamentlager und Drucker", "version": version},
                   "instructions": "SchichtLohn ist das Filamentlager des Nutzers. Erst mit lager_suchen die uid einer Sorte holen, dann lesen oder ändern. "
                                   "Mengen in Gramm, Preise in Euro je kg. Vor Änderungen kurz sagen, was geändert wird."}
        elif methode == "ping":
            erg = {}
        elif methode == "tools/list":
            erg = {"tools": _liste()}
        elif methode == "tools/call":
            w = NACH_NAME.get(p.get("name"))
            if not w:
                raise McpFehler(-32602, f"Unbekanntes Werkzeug {p.get('name')}")
            try:
                daten = w[5](p.get("arguments") or {})
                erg = {"content": [{"type": "text", "text": json.dumps(daten, ensure_ascii=False)}], "structuredContent": daten, "isError": False}
            except McpFehler as e:
                erg = {"content": [{"type": "text", "text": str(e)}], "isError": True}
            except Exception as e:
                erg = {"content": [{"type": "text", "text": "Fehler im SchichtLohn-Server: " + str(e)}], "isError": True}
        elif methode in ("resources/list", "prompts/list"):
            erg = {methode.split("/")[0]: []}
        else:
            raise McpFehler(-32601, f"Unbekannte Methode {methode}")
        return {"jsonrpc": "2.0", "id": mid, "result": erg}
    except McpFehler as e:
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": e.code, "message": str(e)}}
