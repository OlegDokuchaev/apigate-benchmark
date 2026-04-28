# gateway-kong

Kong OSS 3.7 (DB-less) implementation of the same four-route contract as
`../gateway-apigate/` and `../gateway-python/`. One upstream
(`data-service`), one Lua hook for auth, one Lua module for body
validation/rewrite.

Stack: Kong 3.7, `resty.http` + `cjson.safe` in `pre-function` plugins,
`jemalloc` via `LD_PRELOAD`.

## Layout

```
gateway-kong/
├── Dockerfile              # kong:3.7 + libjemalloc2 + LD_PRELOAD
├── kong.yml                # services, routes, pre-function plugins (declarative)
└── lua/
    ├── require_auth.lua    # /my-items hook — POST /verify + keepalive + header swap
    └── transforms.lua      # /items/search validate(), /items/lookup remap()
```

Run only through the repo-root compose file — the Lua modules are mounted
into the container at `/usr/local/share/lua/5.1/`:

```bash
docker compose up --build gateway-kong
# proxy :8090   admin :8091
```

## Public contract

| Method | Path             | Plugin (`pre-function` body)                 |
|--------|------------------|----------------------------------------------|
| GET    | `/items`         | — (bare proxy, baseline)                     |
| GET    | `/my-items`      | `require("require_auth").run()`              |
| POST   | `/items/search`  | `require("transforms").validate()`           |
| POST   | `/items/lookup`  | `require("transforms").remap()`              |

Error envelope is always `{"error": "<message>"}`.

## Authentication flow

`require_auth.lua` runs in the `access` phase of Kong's request pipeline:

1. Read `Authorization`; missing → `401`.
2. `POST http://auth:8001/verify` via `resty.http` with `request_uri`, using
   per-worker keepalive (`keepalive_pool=512`, `keepalive_timeout=120s` —
   4 workers × 512 = 2048 cumulative, aligned with the upstream→data nginx
   pool and with apigate's `AUTH_POOL_MAX_IDLE_PER_HOST=2048` / python's
   `AIOHTTP_LIMIT_PER_HOST=512` × 4 workers). The constant is hardcoded in
   `lua/require_auth.lua` because the `pre-function` Lua sandbox does not
   expose `os.getenv`; tune by editing that file and reloading the gateway.
3. Any transport failure → `401`; any non-2xx → `401` (collapsed so
   upstream status never leaks).
4. Decode `{user_id, email}` with `cjson.safe` (non-throwing); malformed
   payload → `401`.
5. Set `x-user-id` / `x-user-email` for the upstream, clear `Authorization`.

Equivalent of `../gateway-apigate/src/hooks.rs::require_auth` +
`auth_client.rs::verify`, and `../gateway-python/apigate_bench/auth_client.py`.

## Body validation / rewrite

- **`validate()`** — `POST /items/search`, schema
  `{ category?: string, max_price?: number }`. Valid bodies are forwarded
  untouched; malformed input → `400`.
- **`remap()`** — `POST /items/lookup`, public `{ q }` is rewritten to
  internal `{ query, limit: 20, source: "gateway" }` via
  `kong.service.request.set_raw_body(cjson.encode(...))`.

## apigate ↔ Kong mapping

| apigate-rs                                | Kong                                           |
|-------------------------------------------|------------------------------------------------|
| `#[apigate::service]` + routes            | `services[].routes[]`                          |
| `before = [require_auth]`                 | `pre-function` + `lua/require_auth.lua`        |
| `AuthClient` (reqwest + keepalive)        | `resty.http` + `request_uri` keepalive options |
| `json = SearchInput`                      | `transforms.validate()`                        |
| `map = remap_lookup`                      | `transforms.remap()`                           |
| `request_timeout`/`connect_timeout`       | `services[].read_timeout` / `connect_timeout`  |
| `data_backend`                            | `services[].host` / `port`                     |

## Configuration

Set in the root `docker-compose.yml` under the `gateway-kong` service:

| Env var                                    | Value     | Notes                                           |
|--------------------------------------------|-----------|-------------------------------------------------|
| `KONG_DATABASE`                            | `off`     | DB-less mode, declarative config only.          |
| `KONG_DECLARATIVE_CONFIG`                  | `/kong/kong.yml` | Mounted read-only from this folder.      |
| `KONG_PROXY_LISTEN`                        | `0.0.0.0:8080 backlog=1024 reuseport` | Remapped to host `:8090` by compose. `backlog=1024` raises `listen(2)` accept queue from nginx's default 511; `reuseport` gives every worker its own queue and accept-balances at kernel level. Kernel still clamps to `net.core.somaxconn`. |
| `KONG_PROXY_ACCESS_LOG`                    | `off`     | No per-request JSON logging to stdout.          |
| `KONG_ADMIN_ACCESS_LOG`                    | `off`     |                                                 |
| `KONG_NGINX_EVENTS_WORKER_CONNECTIONS`     | `16384`   | Per-worker connection cap. Lifts nginx's 1024 default — at 4 workers × 1024 we run out of slots well before saturating CPU. Must live in the `events {}` block, hence `_EVENTS_` (not `_HTTP_`). |
| `KONG_NGINX_PROXY_TCP_NODELAY`             | `on`      | Disable Nagle on upstream sockets — the four routes carry small JSON, Nagle's 40 ms cork would dominate latency. |
| `KONG_UPSTREAM_KEEPALIVE_POOL_SIZE`        | `512`     | Nginx upstream pool size per worker to data (≈ 2048 cumulative on a 4-core host). |
| `KONG_UPSTREAM_KEEPALIVE_MAX_REQUESTS`     | `10000`   | Recycle connection after N requests; high enough not to age out mid-ramp. |
| `KONG_UPSTREAM_KEEPALIVE_IDLE_TIMEOUT`     | `120`     | Seconds — aligned with apigate `POOL_IDLE_TIMEOUT` and python `AIOHTTP_KEEPALIVE_TIMEOUT` so the three gateways share the same pool aging behaviour. |
| `KONG_UNTRUSTED_LUA_SANDBOX_REQUIRES`      | `require_auth,transforms` | Whitelist the two local modules for the sandboxed `pre-function` plugin. |
| `LD_PRELOAD`                               | `libjemalloc.so.2` | Set by the Dockerfile.                 |

`KONG_NGINX_WORKER_PROCESSES` is intentionally unset, so Kong scales to
`nproc` — matching `tokio::main` in apigate and `granian --workers $(nproc)`
in the Python gateway.

## Validate the declarative config

```bash
docker run --rm \
  -v "$PWD/kong.yml:/kong.yml:ro" \
  -v "$PWD/lua/require_auth.lua:/usr/local/share/lua/5.1/require_auth.lua:ro" \
  -v "$PWD/lua/transforms.lua:/usr/local/share/lua/5.1/transforms.lua:ro" \
  kong:3.7 kong config parse /kong.yml
```

## Design notes

- **jemalloc via `LD_PRELOAD`.** nginx/openresty workers allocate a lot of
  short-lived buffers on the hot path; jemalloc scales past glibc ptmalloc
  once you cross ~8 workers. Same family of fix as `mimalloc` in apigate.
- **`request_uri` with keepalive options.** Simpler than manual
  `connect → request → read_body → set_keepalive`, and returns the socket
  to the per-worker pool automatically. A module-level `AUTH_URL` means
  no string building per request.
- **`cjson.safe`.** The safe variant returns `nil, err` on parse failures
  instead of raising — lets us check `if not parsed` and respond `401`
  without a `pcall`.
- **`strip_path: false`.** data-service receives the full path (`/items`,
  `/my-items`, …). Kong would otherwise strip the matched prefix.
- **Sandbox whitelist.** Kong's `pre-function` runs in a restricted Lua
  sandbox; `require_auth` and `transforms` have to be listed in
  `KONG_UNTRUSTED_LUA_SANDBOX_REQUIRES` before they can `require()` them.
- **Error collapsing in `require_auth`.** Every failure mode (connect
  refused, non-2xx from auth, malformed JSON) ends up as a gateway `401`
  so callers can't distinguish "auth down" from "bad token".
