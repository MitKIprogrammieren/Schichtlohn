"""Katalog des Bambu Lab EU-Shops für die Einkaufsliste.

Liest die Produktseiten der Filamente (eingebettete JSON-LD-Daten mit allen Varianten) und gibt
pro Variante Farbe, Farbcode, Ausführung (Refill / mit Spule), Gewicht, Preis und Verfügbarkeit zurück.
Die Shop-Artikelnummer (sku) braucht der Lesezeichen-Knopf, um die Variante in den Warenkorb zu legen.
"""
import json
import re
import time
import urllib.request

BASIS = "https://eu.store.bambulab.com/de/products/"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
      "(KHTML, like Gecko) Version/18.0 Safari/605.1.15")

# Produktseite -> (Material, Linie) so wie sie im Lager heißen
PRODUKTE = {
    "pla-basic-filament": ("PLA", "Basic"), "pla-matte": ("PLA", "Matt"), "pla-silk-upgrade": ("PLA", "Seide"),
    "pla-sparkle": ("PLA", "Glitzer"), "pla-galaxy": ("PLA", "Galaxy"), "pla-metal": ("PLA", "Metallic"),
    "pla-wood": ("PLA", "Holz"), "pla-marble": ("PLA", "Marmor"), "pla-cf": ("PLA", "CF"),
    "pla-tough-upgrade": ("PLA", "Tough+"), "pla-translucent": ("PLA", "Translucent"), "pla-glow": ("PLA", "Leuchtend"),
    "pla-pure": ("PLA", "Pure"), "pla-aero": ("PLA", "Aero"), "pla-silk-multi-color": ("PLA", "Seide Mehrfarbig"),
    "pla-basic-gradient": ("PLA", "Basic Farbverlauf"),
    "petg-basic": ("PETG", "Basic"), "petg-translucent": ("PETG", "Translucent"), "petg-cf": ("PETG", "CF"),
    "petg-matte": ("PETG", "Matt"),
    "abs-filament": ("ABS", ""), "abs-gf": ("ABS", "GF"), "asa-filament": ("ASA", ""), "asa-cf": ("ASA", "CF"),
    "asa-aero": ("ASA", "Aero"), "pc-filament": ("PC", ""), "pc-fr": ("PC", "FR"),
    "paht-cf": ("PAHT", "CF"), "pa6-cf": ("PA6", "CF"), "pa6-gf": ("PA6", "GF"), "pet-cf": ("PET", "CF"),
    "ppa-cf": ("PPA", "CF"), "pps-cf": ("PPS", "CF"),
    "tpu-95a-hf": ("TPU", "95A HF"), "tpu-for-ams": ("TPU", "für AMS"), "tpu-85a-tpu-90a": ("TPU", "85A/90A"),
    "pva": ("PVA", ""), "support-for-pla-new": ("Support", "für PLA"), "support-for-abs": ("Support", "für ABS"),
    "support-for-pa-pet": ("Support", "für PA/PET"), "support-for-pla-petg": ("Support", "für PLA/PETG"),
}


def _holen(slug):
    req = urllib.request.Request(BASIS + slug, headers={"User-Agent": UA, "Accept-Language": "de-DE,de;q=0.9"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "replace")


def _varianten(html):
    aus = []
    for roh in re.findall(r'<script[^>]*ld\+json[^>]*>(.*?)</script>', html, re.S):
        try:
            b = json.loads(roh)
        except Exception:
            continue
        for v in (b.get("hasVariant") or []) if isinstance(b, dict) else []:
            name = str(v.get("name") or "")
            o = v.get("offers") or {}
            teile = [t.strip() for t in name.split(" - ", 1)[-1].split(" / ")]
            farbe, code = "", ""
            for t in teile:  # das Teil mit „(12345)“ ist die Farbe
                m = re.search(r"\((\d{5})\)", t)
                if m:
                    code = m.group(1)
                    farbe = re.sub(r"\s*\(\d{5}\)\s*", " ", t).strip()
            if not farbe:
                farbe = teile[0] if teile else ""
            rest = " ".join(t for t in teile if not re.search(r"\(\d{5}\)", t)).lower()
            gm = re.search(r"(\d+(?:,\d+)?)\s*kg", rest)
            aus.append({
                "sku": str(v.get("sku") or ""), "farbe": farbe, "code": code,
                "refill": bool(re.search(r"nachf|refill", rest)),
                "gewicht": int(float(gm.group(1).replace(",", ".")) * 1000) if gm else 1000,
                "variante": " / ".join(teile),
                "preis": float(o.get("price") or 0) or None,
                "da": "InStock" in str(o.get("availability") or ""),
                "bild": str(v.get("image") or ""),
            })
    return aus


def katalog():
    """Alle Filamentvarianten des Shops; Seiten, die gerade nicht laden, werden bis zu dreimal versucht."""
    produkte, fehler = [], []
    for slug, (mat, linie) in PRODUKTE.items():
        vs = []
        for versuch in range(4):
            try:
                vs = _varianten(_holen(slug))
            except Exception as e:
                fehler.append(f"{slug}: {e}")
                if "429" in str(e):  # zu viele Abrufe: länger warten
                    time.sleep(20 * (versuch + 1))
            if vs:
                break
            time.sleep(2 + versuch)
        if vs:
            produkte.append({"slug": slug, "material": mat, "linie": linie, "varianten": vs})
        time.sleep(2.5)
    return {"stand": time.strftime("%Y-%m-%d %H:%M"), "produkte": produkte, "fehler": fehler[:20]}
