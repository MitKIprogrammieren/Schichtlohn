"""Druckerkamera direkt vom Bambu-Drucker – ohne Home Assistant.

Zwei Wege, je nach Modell (beide brauchen IP-Adresse und Zugangscode aus den SchichtLohn-Einstellungen):
  A1, A1 mini, P1P, P1S – Einzelbilder (JPEG) über TLS auf Port 6000, etwa eins pro Sekunde
  X1, H2, P2S           – Videostrom RTSPS auf Port 322; ffmpeg macht daraus zwei Bilder pro Sekunde
                          (am Drucker muss „LAN-Modus Liveansicht“ an sein, bei X1 sonst kein Bild)

Die Verbindung läuft nur, solange jemand Bilder abholt; 90 s nach der letzten Anfrage wird sie getrennt,
damit der Drucker nicht dauerhaft eine Kameraverbindung offen hat.
"""
import shutil
import socket
import ssl
import struct
import subprocess
import threading
import time
import urllib.parse

PORT6000 = ("a1", "a1mini", "p1p", "p1s")
LEERLAUF = 90
SOI, EOI = b"\xff\xd8", b"\xff\xd9"


def nutzt_port6000(modell):
    return modell in PORT6000


def auth_paket(code, benutzer="bblp"):
    return (struct.pack("<IIII", 0x40, 0x3000, 0, 0)
            + benutzer.encode("ascii")[:32].ljust(32, b"\0") + str(code).encode("ascii")[:32].ljust(32, b"\0"))


def _genau(sock, n):
    teile, rest = [], n
    while rest > 0:
        b = sock.recv(min(rest, 65536))
        if not b:
            raise ConnectionError("Kamera hat die Verbindung beendet")
        teile.append(b)
        rest -= len(b)
    return b"".join(teile)


def jpeg_teilen(puffer):
    """Fertige JPEG-Bilder aus einem Bytestrom schneiden → (bilder, rest)."""
    bilder = []
    while True:
        a = puffer.find(SOI)
        if a < 0:
            return bilder, b""
        e = puffer.find(EOI, a + 2)
        if e < 0:
            return bilder, puffer[a:]
        bilder.append(puffer[a:e + 2])
        puffer = puffer[e + 2:]


class Kamera:
    def __init__(self, ip, code, modell, log=print):
        self.ip, self.code, self.modell, self.log = ip, code, modell, log
        self.bild = None
        self.t = 0.0
        self.fehler = ""
        self.anfrage = 0.0
        self.thread = None
        self.stop = threading.Event()
        self.neu = threading.Condition()
        self.proc = None

    # ---- abholen
    def holen(self, warten=8.0, max_alter=15.0):
        """Neuestes Bild (JPEG) oder None. Startet die Verbindung bei Bedarf und wartet kurz aufs erste Bild."""
        self.anfrage = time.time()
        self._starten()
        ende = time.time() + warten
        with self.neu:
            while (self.bild is None or time.time() - self.t > max_alter) and time.time() < ende and self.thread and self.thread.is_alive():
                self.neu.wait(0.5)
        return self.bild if self.bild is not None and time.time() - self.t <= max_alter else None

    def naechstes(self, nach, warten=5.0):
        """Auf ein Bild warten, das neuer ist als Zeitpunkt nach (für den Live-Strom) → (bild, t)."""
        self.anfrage = time.time()
        self._starten()
        ende = time.time() + warten
        with self.neu:
            while self.t <= nach and time.time() < ende:
                self.neu.wait(0.5)
        return self.bild, self.t

    def beenden(self):
        self.stop.set()
        self._proc_beenden()

    # ---- Verbindung
    def _starten(self):
        if self.thread and self.thread.is_alive():
            return
        self.stop.clear()
        self.thread = threading.Thread(target=self._lauf, name="kamera-" + self.ip, daemon=True)
        self.thread.start()

    def _merken(self, bild):
        if bild[:2] != SOI or len(bild) < 500:
            return
        with self.neu:
            self.bild, self.t, self.fehler = bild, time.time(), ""
            self.neu.notify_all()

    def _leerlauf(self):
        return self.stop.is_set() or time.time() - self.anfrage > LEERLAUF

    def _lauf(self):
        fehlversuche = 0
        while not self._leerlauf():
            try:
                (self._port6000 if nutzt_port6000(self.modell) else self._rtsp)()
                fehlversuche = 0
            except Exception as e:
                fehlversuche += 1
                text = str(e) or e.__class__.__name__
                if text != self.fehler:
                    self.log(f"Kamera {self.ip}: {text}")
                self.fehler = text
            finally:
                self._proc_beenden()
            if self._leerlauf():
                break
            self.stop.wait(min(30, 2 * fehlversuche + 1))
        with self.neu:
            self.neu.notify_all()

    def _port6000(self):
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        with socket.create_connection((self.ip, 6000), timeout=10) as roh:
            with ctx.wrap_socket(roh, server_hostname=self.ip) as s:
                s.sendall(auth_paket(self.code))
                s.settimeout(15)
                while not self._leerlauf():
                    kopf = _genau(s, 16)
                    groesse = struct.unpack("<I", kopf[:4])[0]
                    if not 0 < groesse < 8_000_000:
                        raise ConnectionError(f"unerwartete Bildgröße {groesse} – Zugangscode richtig?")
                    self._merken(_genau(s, groesse))

    def _rtsp(self):
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            raise RuntimeError("ffmpeg fehlt im Server")
        url = f"rtsps://bblp:{urllib.parse.quote(str(self.code), safe='')}@{self.ip}:322/streaming/live/1"
        self.proc = subprocess.Popen([ffmpeg, "-hide_banner", "-loglevel", "error", "-rtsp_transport", "tcp", "-timeout", "10000000",
                                      "-i", url, "-an", "-vf", "fps=2", "-q:v", "5", "-f", "image2pipe", "-c:v", "mjpeg", "-"],
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL)
        puffer = b""
        while not self._leerlauf():
            b = self.proc.stdout.read1(65536)
            if not b:
                fehler = (self.proc.stderr.read() or b"").decode("utf-8", "replace").strip().splitlines()
                letzte = fehler[-1] if fehler else ""
                if "401" in letzte or "Unauthorized" in letzte:
                    letzte = "Zugangscode abgelehnt"
                elif "Connection refused" in letzte:
                    letzte = "Videostrom aus – am Drucker „LAN-Modus Liveansicht“ einschalten"
                raise ConnectionError(letzte or "Videostrom beendet")
            bilder, puffer = jpeg_teilen(puffer + b)
            for bild in bilder:
                self._merken(bild)
            if len(puffer) > 8_000_000:
                puffer = b""

    def _proc_beenden(self):
        p, self.proc = self.proc, None
        if p and p.poll() is None:
            try:
                p.terminate()
                p.wait(3)
            except Exception:
                try:
                    p.kill()
                except Exception:
                    pass
