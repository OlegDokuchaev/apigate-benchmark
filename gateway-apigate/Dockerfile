FROM rust:1.88-slim-bookworm AS builder
WORKDIR /src

COPY Cargo.toml ./
COPY src ./src
RUN cargo build --release && \
    strip target/release/gateway

FROM gcr.io/distroless/cc-debian12:nonroot
COPY --from=builder /src/target/release/gateway /usr/local/bin/gateway
EXPOSE 8080
USER nonroot:nonroot
ENTRYPOINT ["/usr/local/bin/gateway"]
