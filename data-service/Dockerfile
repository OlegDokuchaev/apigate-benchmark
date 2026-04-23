FROM golang:1.23-alpine AS builder
WORKDIR /src
COPY go.mod ./
RUN go mod download || true
COPY . .
RUN CGO_ENABLED=0 go build -ldflags="-s -w" -o /out/data-service .

FROM gcr.io/distroless/static-debian12:nonroot
COPY --from=builder /out/data-service /data-service
EXPOSE 8002
USER nonroot:nonroot
ENTRYPOINT ["/data-service"]
