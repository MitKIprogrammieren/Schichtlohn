# Konturwerk – Werkzeugeinsätze aus einem Foto (Rust)
FROM rust:1-slim-bookworm AS build
WORKDIR /src
COPY Cargo.toml Cargo.lock ./
COPY src ./src
COPY static ./static
RUN cargo build --release

# ONNX Runtime für die KI-Erkennung (aus dem offiziellen PyPI-Paket, passend zur Plattform)
FROM python:3.12-slim AS ort
RUN pip download "onnxruntime>=1.22,<1.23" --no-deps --only-binary=:all: -d /whl \
 && python -c "import zipfile,glob,re; z=zipfile.ZipFile(glob.glob('/whl/*.whl')[0]); n=[x for x in z.namelist() if re.search(r'capi/libonnxruntime\.so\.[0-9.]+$', x)][0]; open('/libonnxruntime.so','wb').write(z.read(n))"

FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates libheif-examples && rm -rf /var/lib/apt/lists/*
COPY --from=build /src/target/release/konturwerk /usr/local/bin/konturwerk
COPY --from=ort /libonnxruntime.so /usr/local/lib/libonnxruntime.so
ENV KONTURWERK_DATA=/data PORT=8089 ORT_DYLIB_PATH=/usr/local/lib/libonnxruntime.so
VOLUME /data
EXPOSE 8089
HEALTHCHECK --interval=60s --timeout=5s CMD ["/bin/sh", "-c", "exec 3<>/dev/tcp/127.0.0.1/8089 || exit 1"]
CMD ["konturwerk"]
