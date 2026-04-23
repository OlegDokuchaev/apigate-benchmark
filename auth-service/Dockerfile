FROM golang:1.23-alpine AS builder
WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 go build -ldflags="-s -w" -o /out/auth-service .

FROM gcr.io/distroless/static-debian12:nonroot
COPY --from=builder /out/auth-service /auth-service
EXPOSE 8001
USER nonroot:nonroot
ENTRYPOINT ["/auth-service"]
