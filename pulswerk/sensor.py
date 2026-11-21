#!/usr/bin/env python3
"""Pulswerk-Messdienst für den Proxmox-Host (nur lesen).

Liefert unter http://<host>:9105/werte: CPU, RAM, Last, Netz, Temperaturen, Lüfter,
Grafikauslastung (Intel Quick Sync über intel_gpu_top) und die Auslastung jedes Gasts.
Ändert nichts am System."""
import glob
import json
import os
import re
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = int(os.environ.get("PORT", "9105"))
WERTE = {}
GPU = {"video": None, "render": None, "takt": None, "fehlt": None}
SPERRE = threading.Lock()


def lesen(pfad, standard=None):
    try:
        with open(pfad) as f:
            return f.read().strip()
    except OSError:
        return standard


def gpu_schleife():
    """intel_gpu_top -J liefert fortlaufend JSON-Objekte; Klammern zählen und jedes Objekt auswerten."""
    while True:
        try:
            p = subprocess.Popen(["intel_gpu_top", "-J", "-s", "1000"], stdout=subprocess.PIPE,
                                 stderr=subprocess.DEVNULL, text=True, bufsize=1)
        except FileNotFoundError:
            GPU["fehlt"] = "intel-gpu-tools nicht installiert"
            return
        buf, tiefe = "", 0
        while True:
            ch = p.stdout.read(1)
            if not ch:
                break
            if ch == "{":
                tiefe += 1
            if tiefe:
                buf += ch
            if ch == "}":
                tiefe -= 1
                if tiefe == 0:
                    try:
                        d = json.loads(buf)
                        eng = d.get("engines") or {}
                        if isinstance(eng, list):
                            eng = {e.get("name", str(i)): e for i, e in enumerate(eng)}
                        busy = lambda muster: max([float(v.get("busy", 0)) for k, v in eng.items()
                                                    if re.search(muster, k, re.I)] or [0.0])
                        GPU.update(video=round(max(busy(r"^video/"), busy(r"videoenhance")), 1),
                                   render=round(busy(r"render"), 1),
                                   takt=round(float((d.get("frequency") or {}).get("actual", 0))), fehlt=None)
                    except (ValueError, AttributeError):
                        pass
                    buf = ""
        GPU["fehlt"] = "intel_gpu_top beendet"
        time.sleep(5)


def cpu_zeiten():
    t = [int(x) for x in lesen("/proc/stat").splitlines()[0].split()[1:]]
    return sum(t), t[3] + t[4]


def netz():
    rx = tx = 0
    for z in lesen("/proc/net/dev", "").splitlines()[2:]:
        name, werte = z.split(":", 1)
        if name.strip() in ("vmbr0",):
            w = werte.split()
            rx, tx = int(w[0]), int(w[8])
    return rx, tx


def temperaturen():
    erg, luefter = [], []
    for h in sorted(glob.glob("/sys/class/hwmon/hwmon*")):
        name = lesen(h + "/name", "?")
        for t in sorted(glob.glob(h + "/temp*_input")):
            wert = lesen(t)
            if wert and wert.lstrip("-").isdigit():
                label = lesen(t.replace("_input", "_label"), "") or name
                erg.append({"quelle": name, "name": label, "grad": round(int(wert) / 1000, 1)})
        for f in sorted(glob.glob(h + "/fan*_input")):
            wert = lesen(f)
            if wert and wert.isdigit():
                luefter.append({"name": lesen(f.replace("_input", "_label"), "") or name, "upm": int(wert)})
    return erg, luefter


def gaeste():
    """Gäste (LXC und VMs) mit ihren cgroups."""
    erg = []
    for pfad in glob.glob("/sys/fs/cgroup/lxc/*") + glob.glob("/sys/fs/cgroup/qemu.slice/*.scope"):
        m = re.search(r"/(\d+)(?:\.scope)?$", pfad)
        if not m:
            continue
        vmid = m.group(1)
        konf = lesen(f"/etc/pve/lxc/{vmid}.conf") or lesen(f"/etc/pve/qemu-server/{vmid}.conf") or ""
        n = re.search(r"^(?:hostname|name):\s*(\S+)", konf, re.M)
        stat = lesen(pfad + "/cpu.stat", "")
        u = re.search(r"usage_usec (\d+)", stat)
        erg.append({"id": int(vmid), "name": n.group(1) if n else vmid, "usec": int(u.group(1)) if u else 0,
                    "ram": int(lesen(pfad + "/memory.current", "0") or 0)})
    return erg


def mess_schleife():
    kerne = os.cpu_count() or 1
    alt = None
    while True:
        jetzt = time.time()
        ges, leer = cpu_zeiten()
        rx, tx = netz()
        g = gaeste()
        if alt:
            dt = jetzt - alt["zeit"]
            d_ges = ges - alt["ges"]
            cpu = 100 * (1 - (leer - alt["leer"]) / d_ges) if d_ges else 0
            vorher = {x["id"]: x["usec"] for x in alt["gaeste"]}
            gl = [{"id": x["id"], "name": x["name"], "ram": x["ram"],
                   "cpu": round(max(0, x["usec"] - vorher.get(x["id"], x["usec"])) / (dt * 1e6 * kerne) * 100, 1)}
                  for x in g]
            mem = {k: int(v.split()[0]) * 1024 for k, v in
                   (z.split(":", 1) for z in lesen("/proc/meminfo").splitlines())}
            temps, luefter = temperaturen()
            with SPERRE:
                WERTE.update(zeit=round(jetzt, 1), kerne=kerne, cpu=round(cpu, 1),
                             last=[float(x) for x in lesen("/proc/loadavg").split()[:3]],
                             ram=mem["MemTotal"] - mem["MemAvailable"], ram_max=mem["MemTotal"],
                             netz_rx=round((rx - alt["rx"]) * 8 / dt), netz_tx=round((tx - alt["tx"]) * 8 / dt),
                             temperaturen=temps, luefter=luefter, gpu=dict(GPU),
                             gaeste=sorted(gl, key=lambda x: -x["cpu"]))
        alt = {"zeit": jetzt, "ges": ges, "leer": leer, "rx": rx, "tx": tx, "gaeste": g}
        time.sleep(1)


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path.split("?")[0] != "/werte":
            self.send_response(404)
            self.end_headers()
            return
        with SPERRE:
            body = json.dumps(WERTE).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    threading.Thread(target=gpu_schleife, daemon=True).start()
    threading.Thread(target=mess_schleife, daemon=True).start()
    ThreadingHTTPServer(("0.0.0.0", PORT), H).serve_forever()
