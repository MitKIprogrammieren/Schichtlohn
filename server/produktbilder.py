"""Produktbilder für die Rechnungen-Karte.

Die Karte fragt GET /api/produktbild?quelle=…&id=…&n=…&v=… und bekommt ein kleines JPEG (oder 404).
  amazon      Artikelseite amazon.de/dp/<ASIN> → Hauptbild
  aliexpress  Partnerprogramm (aliexpress.affiliate.productdetail.get), sonst Artikelseite → Hauptbild
  bambu       Bambu-Store (Shopify-Suche nach dem Namen), bei Filament das Bild der passenden Farbe
Gefundene Bilder liegen verkleinert neben der Datenbank im Ordner „produktbilder“; ein Fehlschlag wird
eine Weile gemerkt, damit nicht jede Kartenansicht die Shops erneut abfragt. Eine eigene Bildadresse
(PUT /api/produktbild) hat immer Vorrang.
"""
import hashlib
import hmac
import io
import json
import os
import re
import threading
import time
import urllib.parse
import urllib.request

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/130.0 Safari/537.36")
BAMBU_STORE = "https://eu.store.bambulab.com"
GROESSE = 240                 # Kantenlänge der gespeicherten Vorschau
NOCHMAL_NACH = 3 * 86400      # nichts gefunden → frühestens nach 3 Tagen erneut suchen
_lock = threading.Lock()
_gleichzeitig = threading.Semaphore(3)   # höchstens drei Shop-Abfragen auf einmal
_laeuft = {}                  # Schlüssel → Event, damit dieselbe Suche nicht doppelt läuft


class Bilder:
    def __init__(self, ordner, ali_cfg=lambda: {}):
        self.ordner = ordner
        self.datei = os.path.join(ordner, "index.json")
        self.ali_cfg = ali_cfg
        os.makedirs(ordner, exist_ok=True)
        try:
            with open(self.datei, encoding="utf-8") as f:
                self.index = json.load(f)
        except (OSError, ValueError):
            self.index = {}

    # ------------------------------------------------------------ Ablage
    def _speichern(self):
        tmp = self.datei + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.index, f, ensure_ascii=False)
        os.replace(tmp, self.datei)

    @staticmethod
    def schluessel(quelle, pid, name="", variante=""):
        if quelle in ("amazon", "aliexpress") and pid:
            return f"{quelle}:{pid}"
        roh = re.sub(r"\s+", " ", f"{name}|{variante}".lower()).strip()
        return f"{quelle}:{hashlib.sha1(roh.encode()).hexdigest()[:16]}"

    def _pfad(self, k):
        return os.path.join(self.ordner, hashlib.sha1(k.encode()).hexdigest()[:20] + ".jpg")

    # ------------------------------------------------------------ Abruf
    def holen(self, quelle, pid, name="", variante=""):
        """→ JPEG-Bytes oder None"""
        if quelle not in ("amazon", "aliexpress", "bambu"):
            return None
        k = self.schluessel(quelle, pid, name, variante)
        pfad = self._pfad(k)
        e = self.index.get(k) or {}
        if e.get("ok") and os.path.exists(pfad):
            with open(pfad, "rb") as f:
                return f.read()
        if e and not e.get("ok") and time.time() - e.get("zeit", 0) < NOCHMAL_NACH:
            return None
        with _lock:
            ev = _laeuft.get(k)
            selbst = ev is None
            if selbst:
                ev = _laeuft[k] = threading.Event()
        if not selbst:
            ev.wait(40)
            return self.holen_vorhanden(k)
        try:
            url = e.get("eigen") or self._suchen(quelle, pid, name, variante)
            daten = self._laden(url) if url else None
            with _lock:
                self.index[k] = {"ok": bool(daten), "url": url or "", "zeit": time.time(), **({"eigen": e["eigen"]} if e.get("eigen") else {})}
                if daten:
                    with open(pfad, "wb") as f:
                        f.write(daten)
                self._speichern()
            return daten
        finally:
            with _lock:
                _laeuft.pop(k, None)
            ev.set()

    def holen_vorhanden(self, k):
        pfad = self._pfad(k)
        if (self.index.get(k) or {}).get("ok") and os.path.exists(pfad):
            with open(pfad, "rb") as f:
                return f.read()
        return None

    def eigenes(self, quelle, pid, name, variante, url):
        """Bildadresse von Hand setzen (leer = wieder automatisch suchen) → JPEG-Bytes oder None"""
        k = self.schluessel(quelle, pid, name, variante)
        url = str(url or "").strip()
        if url and not re.match(r"^https?://", url):
            raise ValueError("Die Bildadresse muss mit http:// oder https:// beginnen.")
        with _lock:
            self.index.pop(k, None)
            if url:
                self.index[k] = {"eigen": url, "ok": False, "zeit": 0}
            try:
                os.remove(self._pfad(k))
            except OSError:
                pass
            self._speichern()
        if not url:
            return None
        daten = self.holen(quelle, pid, name, variante)
        if not daten:
            raise ValueError("Unter dieser Adresse war kein Bild zu finden.")
        return daten

    # ------------------------------------------------------------ Netz
    @staticmethod
    def _get(url, json_erwartet=False, timeout=15):
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "de-DE,de;q=0.9,en;q=0.6",
                                                   "Accept": "application/json" if json_erwartet else "text/html,image/*,*/*"})
        with _gleichzeitig, urllib.request.urlopen(req, timeout=timeout) as r:
            roh = r.read(8 * 1024 * 1024)
        return json.loads(roh.decode("utf-8") or "{}") if json_erwartet else roh

    def _laden(self, url):
        """Bild holen und auf eine kleine Vorschau verkleinern"""
        try:
            roh = self._get(url)
            from PIL import Image
            img = Image.open(io.BytesIO(roh))
            if img.mode in ("RGBA", "LA", "P"):
                img = img.convert("RGBA")
                weiss = Image.new("RGB", img.size, "white")
                weiss.paste(img, mask=img.split()[-1])
                img = weiss
            img = img.convert("RGB")
            if min(img.size) < 40:   # Platzhalter-Pixel (z. B. 1×1-GIF)
                return None
            img.thumbnail((GROESSE, GROESSE))
            out = io.BytesIO()
            img.save(out, "JPEG", quality=84, optimize=True)
            return out.getvalue()
        except Exception as e:
            print("Produktbild nicht ladbar:", url[:120], e, flush=True)
            return None

    @staticmethod
    def _seitenbild(html):
        t = html.decode("utf-8", "ignore") if isinstance(html, bytes) else html
        for re_ in (r'"hiRes":"(https://[^"]+)"', r'data-old-hires="(https://[^"]+)"', r'"large":"(https://m\.media-amazon\.com/images/I/[^"]+)"',
                    r'<meta[^>]+property="og:image"[^>]+content="([^"]+)"', r'<meta[^>]+content="([^"]+)"[^>]+property="og:image"',
                    r'"imagePathList":\["([^"]+)"'):
            m = re.search(re_, t)
            if m:
                u = m.group(1).replace("\\u002F", "/").replace("\\/", "/")
                return "https:" + u if u.startswith("//") else u
        return None

    def _suchen(self, quelle, pid, name, variante):
        try:
            if quelle == "amazon" and pid:
                return self._seitenbild(self._get(f"https://www.amazon.de/dp/{urllib.parse.quote(pid)}"))
            if quelle == "aliexpress" and pid:
                return self._ali(pid) or self._seitenbild(self._get(f"https://www.aliexpress.com/item/{urllib.parse.quote(pid)}.html"))
            if quelle == "bambu" and name:
                return self._bambu(name, variante)
        except Exception as e:
            print(f"Produktbild ({quelle} {pid or name[:40]}) nicht gefunden:", e, flush=True)
        return None

    def _ali(self, pid):
        cfg = self.ali_cfg() or {}
        if not (cfg.get("key") and cfg.get("secret")):
            return None
        p = {"app_key": cfg["key"], "method": "aliexpress.affiliate.productdetail.get", "sign_method": "sha256",
             "timestamp": str(int(time.time() * 1000)), "v": "2.0", "format": "json", "product_ids": str(pid),
             "target_currency": "EUR", "target_language": "DE", "country": "DE"}
        if cfg.get("tracking"):
            p["tracking_id"] = cfg["tracking"]
        roh = "".join(f"{x}{p[x]}" for x in sorted(p))
        p["sign"] = hmac.new(cfg["secret"].encode(), roh.encode(), hashlib.sha256).hexdigest().upper()
        d = self._get("https://api-sg.aliexpress.com/sync?" + urllib.parse.urlencode(p), json_erwartet=True)
        res = ((d.get("aliexpress_affiliate_productdetail_get_response") or {}).get("resp_result") or {}).get("result") or {}
        prods = (res.get("products") or {}).get("product") or []
        return (prods[0].get("product_main_image_url") if prods else None) or None

    def _bambu(self, name, variante):
        n = re.sub(r"^Pre-order\s+|\s+Final Payment$|\s*\(.*?\)", "", name, flags=re.I).strip()
        q = urllib.parse.urlencode({"q": n, "resources[type]": "product", "resources[limit]": "4"})
        d = self._get(f"{BAMBU_STORE}/search/suggest.json?{q}", json_erwartet=True)
        prods = ((d.get("resources") or {}).get("results") or {}).get("products") or []
        if not prods:
            return None
        nw = set(re.findall(r"[a-z0-9]+", n.lower()))
        prod = max(prods, key=lambda p: len(nw & set(re.findall(r"[a-z0-9]+", str(p.get("title", "")).lower()))))
        bild = prod.get("image") or (prod.get("featured_image") or {}).get("url")
        # Filament & Co.: Bild der gekauften Farbe (Farbnummer oder Farbname aus der Variante)
        v = str(variante or "").lower()
        if v and prod.get("url"):
            try:
                pfad = urllib.parse.urlparse(prod["url"]).path
                p = self._get(f"{BAMBU_STORE}{pfad}.js", json_erwartet=True)
                nr = re.search(r"\((\d{5})\)", v)
                woerter = [w for w in re.findall(r"[a-zäöüß]+", v.split("/")[0]) if len(w) > 2]
                beste, punkte = None, 0
                for var in p.get("variants") or []:
                    t = " ".join(str(var.get(x) or "") for x in ("title", "option1", "option2", "option3", "sku")).lower()
                    s = (5 if nr and nr.group(1) in t else 0) + sum(1 for w in woerter if w in t)
                    fi = var.get("featured_image") or {}
                    if s > punkte and fi.get("src"):
                        beste, punkte = fi["src"], s
                bild = beste or bild
            except Exception:
                pass
        if bild and bild.startswith("//"):
            bild = "https:" + bild
        return bild or None
