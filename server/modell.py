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
