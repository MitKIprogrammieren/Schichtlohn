"""Bambu Filament Manager (Bambu-Cloud): SchichtLohn trägt seine Rollen mit den aktuellen Gramm dort ein.

Bambu Studio und Bambu Handy zeigen den Füllstand einer Rolle sonst nur bei Spulen mit Bambu-Chip. Der Filament Manager
(ab Bambu Studio 2.7) ist eine Bestandsliste im Bambu-Konto; Studio liest sie über dieselbe Schnittstelle wie hier:
  GET    /v1/design-user-service/my/filament/v2?offset=&limit=   → {"hits": [...]}
  POST   /v1/design-user-service/my/filament/v2                  neue Spule
  PUT    /v1/design-user-service/my/filament/v2                  Spule ändern (id im Rumpf)
  DELETE /v1/design-user-service/my/filament/v2/batch            {"ids": [...]}
(Feldnamen wie in Bambu Studio, src/slic3r/GUI/fila_manager/wgtFilaManagerCloudSync.cpp)

Eigene Einträge erkennt SchichtLohn an der Marke „[SL:…]“ in der Notiz – fremde Einträge (Bambu-Chip-Rollen, von Hand
angelegte) werden nie geändert oder gelöscht.
"""
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request

import drucker as drucker_mod

PFAD = "/v1/design-user-service/my/filament/v2"
MARKE = re.compile(r"\[SL:([^\]]{1,120})\]")

# Generische Bambu-Profile je Material (wenn die Sorte keine Bambu-ID hat)
GENERISCH = {"PLA": "GFL99", "PETG": "GFG99", "ABS": "GFB99", "ASA": "GFB98", "TPU": "GFU99", "PC": "GFC99", "PA": "GFN99",
             "PVA": "GFS99", "HIPS": "GFS98", "PET": "GFT99", "PCTG": "GFG97", "PPS": "GFT97"}


class CloudFehler(RuntimeError):
    pass


def _anfrage(c, methode, pfad, rumpf=None, timeout=25):
    url = drucker_mod.CLOUD_API.get(c.get("region", "global"), drucker_mod.CLOUD_API["global"]) + pfad
    daten = None if rumpf is None else json.dumps(rumpf).encode("utf-8")
    kopf = dict(drucker_mod.KOPF, Authorization="Bearer " + c["token"])
    if daten is not None:
        kopf["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=daten, headers=kopf, method=methode)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            b = r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        text = e.read().decode("utf-8", "replace")[:300]
        if e.code == 401:
            raise CloudFehler("Bambu-Anmeldung abgelaufen – unter Bambu-Cloud neu anmelden")
        raise CloudFehler(f"Bambu-Cloud antwortet {e.code} auf {methode}: {text}")
    except (urllib.error.URLError, OSError) as e:
        raise CloudFehler(f"Bambu-Cloud nicht erreichbar: {e}")
    try:
        return json.loads(b) if b.strip() else {}
    except ValueError:
        return {"text": b[:300]}


def liste(c):
    out, off = [], 0
    while True:
        d = _anfrage(c, "GET", PFAD + "?" + urllib.parse.urlencode({"offset": off, "limit": 100}))
        hits = [h for h in (d.get("hits") or []) if isinstance(h, dict)]
        out += hits
        if len(hits) < 100 or off >= 5000:
            return out
        off += 100


def _id_aus(antwort):
    if isinstance(antwort, dict):
        for k in ("id", "spoolId", "filamentId_"):
            if isinstance(antwort.get(k), int):
                return antwort[k]
        for v in antwort.values():
            if isinstance(v, dict):
                i = _id_aus(v)
                if i:
                    return i
    return None


def anlegen(c, rumpf):
    return _id_aus(_anfrage(c, "POST", PFAD, rumpf))


def aendern(c, sid, rumpf):
    b = dict(rumpf, id=int(sid))
    try:
        return _anfrage(c, "PUT", PFAD, b)
    except CloudFehler as e:
        if " 404 " in str(e) or " 405 " in str(e):  # ältere Schnittstelle: id im Pfad
            return _anfrage(c, "PUT", f"{PFAD}/{int(sid)}", b)
        raise


def loeschen(c, ids):
    if ids:
        _anfrage(c, "DELETE", PFAD + "/batch", {"ids": [int(i) for i in ids]})


def farbe(hexwert):
    h = str(hexwert or "").lstrip("#").upper()
    if not re.fullmatch(r"[0-9A-F]{6}([0-9A-F]{2})?", h):
        h = "9E9E9E"
    return "#" + (h if len(h) == 8 else h + "FF")


def rumpf(r):
    """Ein Soll-Eintrag (siehe app.bambu_fm_soll) → Rumpf für die Cloud."""
    typ = (str(r.get("typ") or "PLA").replace("-", " ").split() or ["PLA"])[0].upper()
    fid = r.get("fid") or GENERISCH.get(typ, "GFL99")
    f = farbe(r.get("hex"))
    b = {"createType": "manual", "filamentVendor": r.get("hersteller") or "Generic", "filamentType": r.get("typ") or "PLA",
         "filamentName": r.get("name") or r.get("typ") or "PLA", "filamentId": fid, "isSupport": False,
         "color": f, "colorType": 2, "colors": [f], "trayIdName": "", "rolls": 1,
         "netWeight": max(0, int(round(r["g"]))), "totalNetWeight": max(1, int(round(r.get("voll") or 1000))),
         "note": f"SchichtLohn{' (geschätzt)' if r.get('geschaetzt') else ''} [SL:{r['key']}]", "inPrinter": bool(r.get("dev"))}
    if r.get("dev"):
        b.update({"devId": r["dev"], "amsId": int(r["ams"]), "slotId": str(r["slot"])})
    return b


def _sig(b):
    return json.dumps(b, sort_keys=True)


SLOT_PFAD = "/v1/design-user-service/my/filament/v2/slot-mappings/sync"


def binden(c, devId, mappings):
    """Rollen an AMS-Fächer binden/lösen. mappings: [{amsSn, amsType, amsId, slotId(str), rfid|None, spoolId|None}].
    Gibt {slotId: code} zurück (code 0 = ok, 2 = Rolle unbekannt, 3 = RFID-Konflikt)."""
    if not devId or not mappings:
        return {}
    d = _anfrage(c, "POST", SLOT_PFAD, {"devId": devId, "mappings": mappings})
    return [r for r in ((d.get("results") or []) if isinstance(d, dict) else []) if isinstance(r, dict)]


def _bind_item(r, sid):
    # Studio sendet slotId als String, rfid=null und spoolId für eine von Hand angelegte Rolle (ohne Chip)
    return {"amsId": int(r.get("ams") or 0), "amsSn": str(r.get("amssn") or ""), "amsType": int(r.get("amstyp") or 0),
            "rfid": None, "slotId": str(int(r.get("slot") or 0)), "spoolId": int(sid)}


def _bind_marke(r, sid):
    # eindeutig je Fach+Rolle: ändert sich die Rolle, das Fach oder die Spule, wird neu gebunden
    return f"v1:{r.get('amssn')}:{int(r.get('slot') or 0)}:{int(sid)}"


def abgleichen(c, soll, stand):
    """soll: [{key, g, voll, hersteller, typ, name, fid, hex, dev, ams, slot}]; stand: {key: {"id", "sig"}} (wird angepasst).
    Gibt {"neu", "geaendert", "geloescht", "gleich", "fehler": [...]} zurück."""
    ist = {}
    for h in liste(c):
        m = MARKE.search(str(h.get("note") or ""))
        if m and h.get("id") is not None:
            ist[m.group(1)] = h
    erg = {"neu": 0, "geaendert": 0, "geloescht": 0, "gleich": 0, "gebunden": 0, "fehler": []}
    gesehen = set()
    binds = {}  # devId → [(stand-key, bind-marke, mapping)]; Fach gilt erst nach Cloud-Bestätigung als gebunden

    def merken_binden(r, k, sid):
        if sid and r.get("dev") and r.get("amssn"):
            marke = _bind_marke(r, sid)
            if (stand.get(k) or {}).get("bind") != marke:
                binds.setdefault(r["dev"], []).append((k, marke, _bind_item(r, sid)))

    for r in soll:
        k = r["key"]
        gesehen.add(k)
        b = rumpf(r)
        sig = _sig(b)
        h = ist.get(k)
        vor = stand.get(k) or {}
        if erg["neu"] + erg["geaendert"]:
            time.sleep(0.15)  # die Cloud nicht mit Hunderten Aufrufen auf einmal fluten (erster Lauf mit ganzem Lager)
        try:
            if h is None:
                sid = anlegen(c, b)
                if not sid:  # Antwort ohne id: über die Marke wiederfinden
                    sid = next((x.get("id") for x in liste(c) if (MARKE.search(str(x.get("note") or "")) or [None, None])[1] == k), None)
                stand[k] = {"id": sid, "sig": sig}
                erg["neu"] += 1
                merken_binden(r, k, sid)
            elif vor.get("sig") != sig or int(h.get("netWeight") or -1) != b["netWeight"]:
                # auch neu schreiben, wenn Bambu das Gewicht selbst verstellt hat (bekannter Fehler: springt auf 0 oder 1000 g)
                aendern(c, h["id"], b)
                stand[k] = {"id": h["id"], "sig": sig, "bind": vor.get("bind")}
                erg["geaendert"] += 1
                merken_binden(r, k, h["id"])
            else:
                stand[k] = {"id": h["id"], "sig": sig, "bind": vor.get("bind")}
                erg["gleich"] += 1
                merken_binden(r, k, h["id"])
        except CloudFehler as e:
            erg["fehler"].append(f"{r.get('name') or k}: {e}")
            if "abgelaufen" in str(e):
                raise
    weg = [h["id"] for k, h in ist.items() if k not in gesehen]
    if weg:
        try:
            loeschen(c, weg)
            erg["geloescht"] = len(weg)
        except CloudFehler as e:
            erg["fehler"].append(f"Löschen: {e}")
    for dev, liste_mp in binds.items():
        try:
            res = binden(c, dev, [mp for _, _, mp in liste_mp])
            # Ergebnis je (amsSn, slotId) zuordnen und nur bei Code 0 als gebunden merken
            ok = {(str(x.get("amsSn")), str(x.get("slotId"))): x.get("code") for x in res}
            schlecht = set()
            for k, marke, mp in liste_mp:
                code = ok.get((str(mp["amsSn"]), str(mp["slotId"])))
                if code in (0, None):
                    stand[k]["bind"] = marke
                    erg["gebunden"] += 1
                else:
                    schlecht.add(str(code))
            if schlecht:
                erg["fehler"].append(f"Fach-Bindung {dev}: Code {', '.join(sorted(schlecht))}")
        except CloudFehler as e:
            erg["fehler"].append(f"Fach-Bindung {dev}: {e}")
    for k in list(stand):
        if k not in gesehen:
            stand.pop(k, None)
    return erg
