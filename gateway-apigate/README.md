# gateway-apigate

Rust reference gateway built with `apigate = 0.2.6`, `tokio`, `reqwest`, and `mimalloc`.

## Routes

| Method | Path | apigate feature |
|---|---|---|
| `GET` | `/items` | plain proxy |
| `GET` | `/my-items` | `before = [require_auth]` |
| `POST` | `/items/search` | `json = SearchInput` |
| `POST` | `/items/lookup` | `json = LookupInput`, `map = remap_lookup` |

`/my-items` verifies the bearer token against `auth-service`, injects `x-user-id` and `x-user-email`, then strips `authorization`.

## Config

Defaults are in `.env`; Docker overrides only upstream hostnames via `.env.docker`.

| Env | Value | Purpose |
|---|---:|---|
| `LISTEN_ADDR` | `0.0.0.0:8080` | bind address |
| `AUTH_BACKEND` | `http://127.0.0.1:8001` | auth base URL |
| `DATA_BACKEND` | `http://127.0.0.1:8002` | data base URL |
| `REQUEST_TIMEOUT` | `10s` | data upstream total budget |
| `CONNECT_TIMEOUT` | `3s` | data upstream connect |
| `VERIFY_TIMEOUT` | `3s` | auth `/verify` total budget |
| `POOL_IDLE_TIMEOUT` | `120s` | upstream HTTP keepalive idle |
| `TCP_KEEPALIVE` | `30s` | socket TCP keepalive |
| `DATA_POOL_MAX_IDLE_PER_HOST` | `2048` | data idle pool cap |
| `AUTH_POOL_MAX_IDLE_PER_HOST` | `2048` | auth idle pool cap |
| `LISTEN_BACKLOG` | `4096` | accept queue |

## Fairness Notes

| Area | Value |
|---|---|
| allocator | `mimalloc` |
| worker model | tokio multi-thread, `available_parallelism()` |
| inbound nodelay | `ServeConfig::tcp_nodelay(true)` |
| upstream nodelay | apigate default connector nodelay |
| upstream TCP keepalive | configured through `TCP_KEEPALIVE` for data and auth clients |
| upstream pool size | 2048 per upstream on the 4-vCPU benchmark host |

## Run

```bash
cargo run --release
```

With compose:

```bash
docker compose up --build gateway-apigate
```

## Check

```bash
cargo +1.88.0 check
```
