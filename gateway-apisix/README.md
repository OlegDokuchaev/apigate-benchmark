# gateway-apisix

Apache APISIX 3.16 standalone gateway. Mirrors the Kong contract with APISIX YAML and Lua.

## Files

| File | Purpose |
|---|---|
| `config.yaml` | APISIX/nginx runtime tuning |
| `apisix.yaml` | routes, upstream, plugin calls |
| `lua/require_auth.lua` | `/my-items` auth hook |
| `lua/transforms.lua` | search validation and lookup rewrite |
| `Dockerfile` | APISIX + jemalloc |

## Routes

| Method | Path | APISIX implementation |
|---|---|---|
| `GET` | `/items` | plain proxy |
| `GET` | `/my-items` | `serverless-pre-function` -> `require_auth.run(...)` |
| `POST` | `/items/search` | `serverless-pre-function` -> `transforms.validate()` |
| `POST` | `/items/lookup` | `serverless-pre-function` -> `transforms.remap()` |

Lua `max_price` validation uses `is_integer(number)` after `cjson` decode.

## Key Config

| Setting | Value |
|---|---:|
| mode | standalone YAML |
| workers | `worker_processes: auto` |
| listen | `9080`, backlog `1024`, reuseport enabled |
| `worker_connections` | `16384` |
| access log | off |
| inbound keepalive | `120s`, `1000000` requests |
| upstream pool size | `512` per worker |
| upstream pool idle | `120s` |
| upstream request cap | `1000000` |
| upstream connect/read/send | `3s / 10s / 10s` |
| auth timeout | `3000ms` |
| auth keepalive | `120000ms`, pool `512` per worker |
| TCP keepalive | `proxy_socket_keepalive on`, container `tcp_keepalive_time=30` |
| allocator | jemalloc |

On a 4-vCPU host, `512 x 4 = 2048` upstream idle slots per upstream.

## Run

```bash
docker compose up --build gateway-apisix
```

## Check

```bash
docker compose run --rm --no-deps gateway-apisix apisix test
luac -p gateway-apisix/lua/require_auth.lua gateway-apisix/lua/transforms.lua
```
