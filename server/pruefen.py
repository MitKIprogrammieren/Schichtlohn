"""Prüft beim Bauen, ob die genaueren Lesemodelle mit dieser Plattform funktionieren.
Wenn nicht, werden sie entfernt und der Server nutzt die eingebauten Modelle."""
import os
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFont

d = "/app/modelle"
det, rec = os.path.join(d, "ocr_det.onnx"), os.path.join(d, "ocr_rec.onnx")
if not (os.path.exists(det) and os.path.exists(rec)):
    sys.exit(0)
try:
    from rapidocr_onnxruntime import RapidOCR
    o = RapidOCR(det_model_path=det, rec_model_path=rec)
    img = Image.new("RGB", (640, 160), "white")
    try:
        f = ImageFont.truetype("DejaVuSans.ttf", 64)
    except Exception:
        f = ImageFont.load_default()
    ImageDraw.Draw(img).text((20, 40), "PLA Basic", fill="black", font=f)
    res, _ = o(np.asarray(img)[:, :, ::-1])
    txt = " ".join(r[1] for r in (res or []))
    print("Probe gelesen:", txt)
    if "PLA" not in txt.upper():
        raise RuntimeError("Probetext nicht erkannt")
except Exception as e:
    print("Genauere Lesemodelle nicht nutzbar, nehme eingebaute:", e)
    for p in (det, rec):
        try:
            os.remove(p)
        except OSError:
            pass
