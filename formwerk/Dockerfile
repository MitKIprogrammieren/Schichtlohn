# Formwerk – Großformat-Generator
FROM rust:1-slim AS build
WORKDIR /src
COPY Cargo.toml Cargo.lock ./
COPY src ./src
COPY static ./static
RUN cargo build --release

FROM debian:bookworm-slim
COPY --from=build /src/target/release/formwerk /usr/local/bin/formwerk
ENV FORMWERK_DATA=/data PORT=8097
VOLUME /data
EXPOSE 8097
HEALTHCHECK --interval=60s --timeout=5s CMD ["/bin/sh", "-c", "exec 3<>/dev/tcp/127.0.0.1/8097 || exit 1"]
CMD ["formwerk"]
