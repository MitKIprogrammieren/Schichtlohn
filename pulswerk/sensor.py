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
# Turbo schalten dürfen nur Pulswerk (CT 100) und der Host selbst
ERLAUBT = set(os.environ.get("ERLAUBT", "192.168.1.30,127.0.0.1").split(","))
TURBO_DATEI = "/etc/pulswerk-turbo"
NO_TURBO = "/sys/devices/system/cpu/intel_pstate/no_turbo"
BOOST = "/sys/devices/system/cpu/cpufreq/boost"


def turbo_lesen():
    if os.path.exists(NO_TURBO):
        return lesen(NO_TURBO) == "0"
    if os.path.exists(BOOST):
        return lesen(BOOST) == "1"
    return None


def turbo_setzen(an):
    if os.path.exists(NO_TURBO):
        pfad, wert = NO_TURBO, "0" if an else "1"
    elif os.path.exists(BOOST):
        pfad, wert = BOOST, "1" if an else "0"
    else:
        return False
    with open(pfad, "w") as f:
        f.write(wert)
    try:
        with open(TURBO_DATEI, "w") as f:
            f.write("an" if an else "aus")
    except OSError:
        pass
    return True
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
    """Gesamt und je Kern: (summe, leerlauf)."""
    erg = []
    for z in lesen("/proc/stat").splitlines():
        if not z.startswith("cpu"):
            break
        t = [int(x) for x in z.split()[1:]]
        erg.append((sum(t), t[3] + t[4]))
    return erg


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


def prozesse():
    """CPU-Zeit aller Prozesse (Host und Gäste teilen sich den Kernel): {pid: (name, ticks, ctid)}."""
    erg = {}
    for d in os.listdir("/proc"):
        if not d.isdigit():
            continue
        st = lesen(f"/proc/{d}/stat", "")
        if not st:
            continue
        try:
            name = st[st.index("(") + 1:st.rindex(")")]
            felder = st[st.rindex(")") + 2:].split()
            ticks = int(felder[11]) + int(felder[12])
        except (ValueError, IndexError):
            continue
        cg = lesen(f"/proc/{d}/cgroup", "")
        m = re.search(r"/lxc/(\d+)/", cg) or re.search(r"/qemu\.slice/(\d+)\.scope", cg)
        erg[d] = (name, ticks, int(m.group(1)) if m else 0)
    return erg


def kern_gruppen():
    """Welche Rechen-Threads gehören zu welchem echten Kern (Hyper-Threading)."""
    gruppen = {}
    for p in sorted(glob.glob("/sys/devices/system/cpu/cpu[0-9]*/topology/core_id")):
        n = int(re.search(r"cpu(\d+)/", p).group(1))
        gruppen.setdefault(int(lesen(p, "0")), []).append(n)
    return [gruppen[k] for k in sorted(gruppen)]


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
    hz = os.sysconf("SC_CLK_TCK")
    gruppen = kern_gruppen()
    alt = None
    while True:
        jetzt = time.time()
        zeiten = cpu_zeiten()
        ges, leer = zeiten[0]
        rx, tx = netz()
        g = gaeste()
        pr = prozesse()
        if alt:
            dt = jetzt - alt["zeit"]
            d_ges = ges - alt["ges"]
            cpu = 100 * (1 - (leer - alt["leer"]) / d_ges) if d_ges else 0
            je_thread = []
            for (g1, l1), (g0, l0) in zip(zeiten[1:], alt["zeiten"][1:]):
                je_thread.append(100 * (1 - (l1 - l0) / (g1 - g0)) if g1 > g0 else 0)
            # je echtem Kern: Mittel seiner Threads
            je_kern = [round(sum(je_thread[t] for t in grp if t < len(je_thread)) / len(grp), 1) for grp in gruppen] or \
                [round(x, 1) for x in je_thread]
            namen = {x["id"]: x["name"] for x in g}
            top = []
            for pid, (name, ticks, ct) in pr.items():
                vorher = alt["pr"].get(pid)
                if vorher and vorher[0] == name and ticks > vorher[1]:
                    top.append({"name": name, "gast": namen.get(ct, "Proxmox" if not ct else str(ct)),
                                "cpu": round((ticks - vorher[1]) / hz / dt / kerne * 100, 1)})
            sammel = {}
            for t in top:
                k = (t["name"], t["gast"])
                sammel[k] = sammel.get(k, 0) + t["cpu"]
            top = sorted(({"name": k[0], "gast": k[1], "cpu": round(v, 1)} for k, v in sammel.items()),
                         key=lambda x: -x["cpu"])[:8]
            vorher = {x["id"]: x["usec"] for x in alt["gaeste"]}
            gl = [{"id": x["id"], "name": x["name"], "ram": x["ram"],
                   "cpu": round(max(0, x["usec"] - vorher.get(x["id"], x["usec"])) / (dt * 1e6 * kerne) * 100, 1)}
                  for x in g]
            mem = {k: int(v.split()[0]) * 1024 for k, v in
                   (z.split(":", 1) for z in lesen("/proc/meminfo").splitlines())}
            temps, luefter = temperaturen()
            with SPERRE:
                WERTE.update(zeit=round(jetzt, 1), kerne=kerne, cpu=round(cpu, 1), kerne_last=je_kern, prozesse=top, turbo=turbo_lesen(),
                             last=[float(x) for x in lesen("/proc/loadavg").split()[:3]],
                             ram=mem["MemTotal"] - mem["MemAvailable"], ram_max=mem["MemTotal"],
                             netz_rx=round((rx - alt["rx"]) * 8 / dt), netz_tx=round((tx - alt["tx"]) * 8 / dt),
                             temperaturen=temps, luefter=luefter, gpu=dict(GPU),
                             gaeste=sorted(gl, key=lambda x: -x["cpu"]))
        alt = {"zeit": jetzt, "ges": ges, "leer": leer, "zeiten": zeiten, "pr": {k: (v[0], v[1]) for k, v in pr.items()}, "rx": rx, "tx": tx, "gaeste": g}
        time.sleep(1)


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        if self.path.split("?")[0] != "/turbo" or self.client_address[0] not in ERLAUBT:
            self.send_response(403)
            self.end_headers()
            return
        n = int(self.headers.get("Content-Length") or 0)
        try:
            an = bool(json.loads(self.rfile.read(min(n, 100)) or b"{}").get("an"))
            ok = turbo_setzen(an)
        except (ValueError, OSError):
            ok = False
        body = json.dumps({"ok": ok, "turbo": turbo_lesen()}).encode()
        self.send_response(200 if ok else 500)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

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
    # gespeicherte Turbo-Wahl nach Neustart wieder anwenden
    if lesen(TURBO_DATEI) in ("an", "aus"):
        try:
            turbo_setzen(lesen(TURBO_DATEI) == "an")
        except OSError:
            pass
    threading.Thread(target=gpu_schleife, daemon=True).start()
    threading.Thread(target=mess_schleife, daemon=True).start()
    ThreadingHTTPServer(("0.0.0.0", PORT), H).serve_forever()
