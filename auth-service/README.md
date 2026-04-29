# auth-service

Go/fasthttp JWT service used by every gateway benchmark.

## API

| Method | Path | Body | Response |
|---|---|---|---|
| `GET` | `/health` | - | `{"ok":true}` |
| `POST` | `/register` | `{email,password}` | `201`, or `409` if user exists |
| `POST` | `/login` | `{email,password}` | `{access_token}` |
| `POST` | `/verify` | header `Authorization: Bearer ...` | `{user_id,email}` |

## Config

| Env | Default |
|---|---|
| `LISTEN_ADDR` | `:8001` |
| `JWT_SECRET` | `dev-secret-change-me` |
| `JWT_TTL_MINUTES` | `60` |

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
docker compose up --build auth
```
