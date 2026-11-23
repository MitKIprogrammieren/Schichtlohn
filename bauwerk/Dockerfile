# Bauwerk-Server für den NUC (Oberfläche + Rust-Kern + MCP unter /mcp)
FROM rust:1-bookworm AS bau
WORKDIR /src
COPY Cargo.toml Cargo.lock ./
COPY crates crates
COPY web web
RUN cargo build --release -p bauwerk && strip target/release/bauwerk

FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl && rm -rf /var/lib/apt/lists/*
COPY --from=bau /src/target/release/bauwerk /usr/local/bin/bauwerk
ENV PORT=8088 BAUWERK_DATEN=/daten TZ=Europe/Berlin
VOLUME /daten
EXPOSE 8088
HEALTHCHECK --interval=60s --timeout=5s CMD curl -fs http://127.0.0.1:8088/gesund || exit 1
CMD ["bauwerk", "server", "--daten", "/daten"]
