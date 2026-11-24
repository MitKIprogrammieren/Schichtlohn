"""Werke-Lader: startet den bisherigen Server (/app/start.py) und hängt die Erweiterungen aus diesem Ordner an.

start.py lädt beim Start „pve_werkzeuge“ und ruft dessen erweitern(sw) auf. Der Lader schiebt dort eine Hülle
dazwischen: Sie lädt zuerst die echten Proxmox-Werkzeuge und danach jede Datei aus erweiterungen/.
Geht eine Erweiterung schief, läuft Werke ohne sie weiter.
"""
import glob
import importlib.util
import os
import runpy
import sys
import types

sys.path.insert(0, "/app")
ORDNER = os.path.dirname(os.path.abspath(__file__))


def _laden(pfad, name):
    spec = importlib.util.spec_from_file_location(name, pfad)
    modul = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modul)
    return modul


def erweitern(sw):
    teile = []
    try:
        teile.append(str(_laden("/app/pve_werkzeuge.py", "pve_werkzeuge_echt").erweitern(sw)))
    except Exception as e:
        teile.append("NICHT geladen: " + repr(e))
    for pfad in sorted(glob.glob(os.path.join(ORDNER, "erweiterungen", "*.py"))):
        name = os.path.basename(pfad)[:-3]
        try:
            teile.append(f"{name}: {_laden(pfad, 'werke_' + name).erweitern(sw)}")
        except Exception as e:
            teile.append(f"{name} NICHT geladen: {e!r}")
    return " · ".join(teile)


huelle = types.ModuleType("pve_werkzeuge")
huelle.erweitern = erweitern
sys.modules["pve_werkzeuge"] = huelle
runpy.run_path("/app/start.py", run_name="__main__")
