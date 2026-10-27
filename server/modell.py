"""Lädt beim Bauen des Containers MobileNetV2 (ONNX Model Zoo, Apache-2.0) und macht die
Merkmalsschicht (Global Average Pool, 1280 Werte) als zusätzlichen Ausgang verfügbar."""
import os
import sys
import urllib.request

import onnx

URL = "https://media.githubusercontent.com/media/onnx/models/main/validated/vision/classification/mobilenet/model/mobilenetv2-12.onnx"
ziel = sys.argv[1] if len(sys.argv) > 1 else "/app/modelle/mnv2_merkmale.onnx"
os.makedirs(os.path.dirname(ziel), exist_ok=True)
roh = ziel + ".roh"
urllib.request.urlretrieve(URL, roh)
m = onnx.load(roh)
m.graph.output.append(onnx.helper.make_tensor_value_info("464", onnx.TensorProto.FLOAT, None))
onnx.save(m, ziel)
os.remove(roh)
print("Modell gespeichert:", ziel, os.path.getsize(ziel) // 1024, "KB")

# Genaueres Lesemodell (PaddleOCR PP-OCRv4: Erkennung mobil, Lesen Server-Variante), konvertiert von RapidAI.
# Schlägt der Download fehl, nimmt der Server die eingebauten kleineren Modelle.
OCR = {
    "ocr_det.onnx": "https://huggingface.co/SWHL/RapidOCR/resolve/main/PP-OCRv4/ch_PP-OCRv4_det_infer.onnx",
    "ocr_rec.onnx": "https://huggingface.co/SWHL/RapidOCR/resolve/main/PP-OCRv4/ch_PP-OCRv4_rec_server_infer.onnx",
    "ocr_rec_mobil.onnx": "https://huggingface.co/SWHL/RapidOCR/resolve/main/PP-OCRv4/ch_PP-OCRv4_rec_infer.onnx",
}
for name, url in OCR.items():
    try:
        p = os.path.join(os.path.dirname(ziel), name)
        urllib.request.urlretrieve(url, p)
        print("Lesemodell gespeichert:", p, os.path.getsize(p) // 1024, "KB")
    except Exception as e:
        print("Lesemodell nicht geladen (", name, "):", e)

# Filament-Datenbank als Grundversion mitliefern (offline nutzbar); aktualisierbar über die App
try:
    p = os.path.join(os.path.dirname(ziel), "filamentdb.json")
    urllib.request.urlretrieve("https://mitkiprogrammieren.github.io/Schichtlohn/filamentdb.json", p)
    print("Filament-Datenbank mitgeliefert:", os.path.getsize(p) // 1024, "KB")
except Exception as e:
    print("Filament-Datenbank nicht mitgeliefert:", e)
