# Stufe 1 läuft immer nativ auf dem Build-Rechner: Bildmodell holen und Merkmalsschicht freilegen
FROM --platform=$BUILDPLATFORM python:3.12-slim AS modell
RUN pip install --no-cache-dir onnx==1.19.1
COPY modell.py .
RUN python modell.py /modelle/mnv2_merkmale.onnx

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=8093 DB=/daten/schichtlohn.db
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
 && pip install --no-cache-dir --no-deps rapidocr_onnxruntime==1.2.3 \
 && python -c "from rapidocr_onnxruntime import RapidOCR; RapidOCR()"
COPY --from=modell /modelle /app/modelle
COPY app.py .
VOLUME /daten
EXPOSE 8093
HEALTHCHECK --interval=60s --timeout=5s CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8093/')" || exit 1
CMD ["python", "app.py"]
