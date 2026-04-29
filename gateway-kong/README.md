# gateway-kong

Kong 3.7 DB-less gateway. Route logic is in declarative `kong.yml` plus two Lua modules.

## Files

| File | Purpose |
|---|---|
| `kong.yml` | service, routes, timeouts, plugin calls |
| `lua/require_auth.lua` | `/my-items` auth hook |
| `lua/transforms.lua` | search validation and lookup rewrite |
| `Dockerfile` | Kong + jemalloc |

## Routes

| Method | Path | Kong implementation |
|---|---|---|
| `GET` | `/items` | plain proxy |
| `GET` | `/my-items` | `pre-function` -> `require_auth.run(...)` |
| `POST` | `/items/search` | `pre-function` -> `transforms.validate()` |
| `POST` | `/items/lookup` | `pre-function` -> `transforms.remap()` |

Lua `max_price` validation uses `is_integer(number)` after `cjson` decode.

## Key Config

| Setting | Value |
|---|---:|
| workers | `worker_processes=auto` |
| listen | `0.0.0.0:8080 backlog=1024 reuseport` |
| `worker_connections` | `16384` |
| access log | off |
| inbound keepalive | `120s`, `1000000` requests |
| upstream pool size | `512` per worker |
| upstream pool idle | `120s` |
| upstream request cap | `1000000` |
| upstream connect/read/write | `3s / 10s / 10s` |
| auth timeout | `3000ms` |
| auth keepalive | `120000ms`, pool `512` per worker |
| TCP keepalive | `proxy_socket_keepalive on`, container `tcp_keepalive_time=30` |
| allocator | jemalloc |

On a 4-vCPU host, `512 x 4 = 2048` upstream idle slots per upstream.

## Run

```bash
docker compose up --build gateway-kong
```

## Check

```bash
docker compose run --rm --no-deps gateway-kong kong config parse /kong/kong.yml
luac -p gateway-kong/lua/require_auth.lua gateway-kong/lua/transforms.lua
```
