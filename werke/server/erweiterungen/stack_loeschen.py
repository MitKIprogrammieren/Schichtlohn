"""Werke-Erweiterung: gestoppte Stacks löschen.

Der Stack wird mit „docker compose down“ abgebaut (Container und Netz, Volumes bleiben) und sein Ordner
nach /opt/stacks/_geloescht/<name>-<zeit> verschoben. Nichts wird endgültig gelöscht.
Laufende Stacks, Werke selbst und Stacks außerhalb von /opt/stacks lassen sich nicht löschen.
"""
import json
import os
import shutil
import time
import urllib.parse

PAPIERKORB = "_geloescht"


def stack_loeschen(sw, name):
    st = sw.stack_holen(name)
    if st.get("selbst"):
        raise RuntimeError("Werke kann sich nicht selbst löschen.")
    if st.get("extern") or os.path.dirname(os.path.abspath(st["ordner"])) != os.path.abspath(sw.STACKS):
        raise RuntimeError(f"{st['name']} liegt außerhalb von {sw.STACKS} und wird hier nicht gelöscht.")
    if st.get("laufen"):
        raise RuntimeError(f"{st['name']} läuft noch – bitte zuerst stoppen.")
    ok, txt = sw._compose(st, "down", "--remove-orphans", timeout=180)
    if not ok:
        return {"ok": False, "text": "Abbauen hat nicht geklappt:\n" + txt}
    korb = os.path.join(sw.STACKS, PAPIERKORB)
    os.makedirs(korb, exist_ok=True)
    ziel = os.path.join(korb, f"{st['name']}-{time.strftime('%Y%m%d-%H%M%S')}")
    shutil.move(st["ordner"], ziel)
    return {"ok": True, "text": f"{st['name']} gelöscht. Der Ordner liegt jetzt in {ziel}.", "papierkorb": ziel}


def erweitern(sw):
    H = sw.Handler
    alt_post = H.do_POST

    def do_POST(self):
        teile = urllib.parse.urlparse(self.path).path.strip("/").split("/")
        if not (len(teile) == 4 and teile[:2] == ["api", "stacks"] and teile[3] == "loeschen"):
            return alt_post(self)
        laenge = int(self.headers.get("Content-Length") or 0)
        if laenge:
            self.rfile.read(laenge)
        if not self._angemeldet():
            return self._antwort(401, {"fehler": "anmelden"})
        name = urllib.parse.unquote(teile[2])
        schluessel = "stack:" + name
        with sw._lock:
            if sw.AKTION.get(schluessel):
                return self._antwort(409, {"fehler": "Läuft schon: " + sw.AKTION[schluessel]})
            sw.AKTION[schluessel] = "loeschen"
        try:
            return self._antwort(200, stack_loeschen(sw, name))
        except Exception as e:
            return self._antwort(400, {"fehler": str(e)})
        finally:
            sw.AKTION.pop(schluessel, None)

    H.do_POST = do_POST

    def _w_loeschen(a):
        return stack_loeschen(sw, str(a["name"]))

    neu = [
        ("stack_loeschen",
         "Einen gestoppten Stack löschen: Container und Netz abbauen (Volumes bleiben) und den Ordner nach "
         "/opt/stacks/_geloescht/ verschieben. Laufende Stacks, Werke selbst und Stacks außerhalb von /opt/stacks gehen nicht. "
         "Vorher beim Nutzer nachfragen.",
         {"name": sw.S_NAME}, ["name"], False, _w_loeschen),
    ]
    sw.WERKZEUGE.extend(neu)
    sw.W_NACH_NAME.update({w[0]: w for w in neu})
    return len(neu)
