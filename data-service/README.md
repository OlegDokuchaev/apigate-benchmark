# data-service

Go/fasthttp catalogue backend. It trusts identity headers injected by the gateway.

## API

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/health` | health check |
| `GET` | `/items` | full catalogue |
| `GET` | `/my-items` | catalogue filtered by `x-user-id` |
| `POST` | `/items/search` | search by `{category?, max_price?}` |
| `POST` | `/items/lookup` | internal lookup body `{query, limit, source}` |

`/items/search` and `/items/lookup` assume the gateway already validated or rewrote the request.

## Config

| Env | Default |
|---|---|
| `LISTEN_ADDR` | `:8002` |

## Runtime Tuning

| Setting | Value |
|---|---:|
| `ReadTimeout` | 10s |
| `WriteTimeout` | 10s |
| `IdleTimeout` | 120s |
| `TCPKeepalive` | true |
| `TCPKeepalivePeriod` | 30s |

These values match gateway upstream timeout/keepalive settings.

## Run

```bash
go run .
```

With compose:

```bash
docker compose up --build data
```
