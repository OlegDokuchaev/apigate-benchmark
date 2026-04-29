# gateway-apisix

Apache APISIX 3.16 standalone implementation of the same four-route contract as
`../gateway-apigate/`, `../gateway-kong/`, and `../gateway-python/`. One
upstream (`data-service`), one Lua hook for auth, one Lua module for body
validation/rewrite.

Stack: Apache APISIX 3.16, `resty.http` + `cjson.safe` in
`serverless-pre-function` plugins, `jemalloc` via `LD_PRELOAD`.

## Layout

```
gateway-apisix/
├── Dockerfile              # apache/apisix:3.16.0-debian + libjemalloc2 + LD_PRELOAD
├── config.yaml             # APISIX/nginx standalone tuning
├── apisix.yaml             # routes, upstream, serverless-pre-function plugins
└── lua/
    ├── require_auth.lua    # /my-items hook — POST /verify + keepalive + header swap
    └── transforms.lua      # /items/search validate(), /items/lookup remap()
```

Run only through the repo-root compose file — the APISIX config and Lua modules
are mounted into the container:

```bash
docker compose up --build gateway-apisix
# proxy :8093
```

## Public contract

| Method | Path             | Plugin (`serverless-pre-function` body) |
|--------|------------------|------------------------------------------|
| GET    | `/items`         | — (bare proxy, baseline)                 |
| GET    | `/my-items`      | cached local `require_auth.run()`        |
| POST   | `/items/search`  | cached local `transforms.validate()`     |
| POST   | `/items/lookup`  | cached local `transforms.remap()`        |

Error envelope is always `{"error": "<message>"}`.

## Authentication flow

`require_auth.lua` runs in the APISIX access phase:

1. Read `Authorization`; missing -> `401`.
2. `POST http://auth:8001/verify` via `resty.http` with `request_uri`, using
   per-worker keepalive (`keepalive_pool=512`, `keepalive_timeout=120s`).
   On a 4-worker host this is 2048 cumulative, aligned with Kong's Lua auth
   pool and with the apigate / python per-host caps.
3. Any transport failure -> `401`; any non-2xx -> `401` (collapsed so
   upstream status never leaks).
4. Decode `{user_id, email}` with `cjson.safe`; malformed payload -> `401`.
5. Set `x-user-id` / `x-user-email` for the upstream, clear `Authorization`.

## Body validation / rewrite

- **`validate()`** — `POST /items/search`, schema
  `{ category?: string, max_price?: integer }`. Valid bodies are forwarded
  untouched; malformed input -> `400`.
- **`remap()`** — `POST /items/lookup`, public `{ q }` is rewritten to
  internal `{ query, limit: 20, source: "gateway" }` via `ngx.req.set_body_data`.

## apigate / Kong -> APISIX mapping

| apigate / Kong                           | APISIX                                           |
|------------------------------------------|--------------------------------------------------|
| `#[apigate::service]` / `services[].routes[]` | `routes[]` in `apisix.yaml`               |
| `before = [require_auth]` / `pre-function` | `serverless-pre-function` + `lua/require_auth.lua` |
| `AuthClient` / Kong `resty.http`         | `resty.http` + `request_uri` keepalive options   |
| `json = SearchInput` / `transforms.validate()` | `transforms.validate()`                    |
| `map = remap_lookup` / `transforms.remap()` | `transforms.remap()`                       |
| `request_timeout` / Kong timeouts        | `upstream.timeout.{connect,send,read}`           |
| `data_backend` / Kong service            | `upstreams[].nodes["data:8002"]`                 |

## Configuration

Set in the root `docker-compose.yml` under the `gateway-apisix` service and in
this directory's config files:

| Setting                                      | Value     | Notes                                           |
|----------------------------------------------|-----------|-------------------------------------------------|
| `APISIX_STAND_ALONE`                         | `true`    | Docker standalone mode.                         |
| `deployment.role_data_plane.config_provider` | `yaml`    | File-driven config from `conf/apisix.yaml`.     |
| `apisix.node_listen`                         | `9080`, `backlog: 1024` | Remapped to host `:8093`; with reuseport and 4 workers gives 4096 cumulative backlog. |
| `apisix.enable_reuseport`                    | `true`    | Same accept scaling shape as Kong.              |
| `nginx_config.worker_processes`              | `auto`    | Scales to available CPU cores.                  |
| `nginx_config.event.worker_connections`      | `16384`   | Same per-worker cap as Kong.                    |
| `nginx_config.http.enable_access_log`        | `false`   | No per-request access logging.                  |
| `nginx_config.http.keepalive_timeout`        | `120s`    | Client -> gateway HTTP keep-alive idle timeout. Mirrors Kong inbound keep-alive and the upstream pool idle. |
| `nginx_config.http.keepalive_requests`       | `1000000` | Recycle inbound client connections after N requests; high enough not to age sockets during the matrix. |
| `nginx_config.http_server_configuration_snippet` | `proxy_socket_keepalive on;` | Enables TCP `SO_KEEPALIVE` on APISIX proxy -> data upstream sockets. Probe timing comes from the compose service sysctl `net.ipv4.tcp_keepalive_time=30`. |
| `upstream.timeout.connect`                   | `3`       | Data upstream connect timeout in seconds.       |
| `upstream.timeout.read/send`                 | `10`      | Data upstream total read/write budget shape.    |
| `upstream.keepalive_pool.size`               | `512`     | Per-worker pool to data (2048 cumulative on 4 workers). |
| `upstream.keepalive_pool.idle_timeout`       | `120`     | Seconds; aligned with all other gateways.       |
| `upstream.keepalive_pool.requests`           | `1000000` | Same request-count aging as Kong; high enough not to age sockets during the matrix. |
| `LD_PRELOAD`                                 | `libjemalloc.so.2` | Set by the Dockerfile.                 |

## Validate the config

```bash
docker compose build gateway-apisix
docker compose run --rm gateway-apisix apisix test
```

## Design notes

- **Standalone YAML.** No etcd/Admin API on the hot path. APISIX loads
  `conf/apisix.yaml` directly; the file must end with `#END`.
- **jemalloc via `LD_PRELOAD`.** Same allocator family as the Kong and Python
  gateways for nginx/openresty worker allocation patterns.
- **Module caching in serverless functions.** `apisix.yaml` stores
  `local run = require(...).run` before returning the function, so per-request
  work is only a Lua closure call, not a `require()` lookup.
- **`request_uri` with keepalive options.** Mirrors Kong's auth hook and returns
  the `/verify` socket to the per-worker pool automatically. Auth URL, timeout,
  keep-alive idle, and pool size are passed from `apisix.yaml` into
  `require_auth.run(...)`.
- **`cjson.safe`.** Non-throwing JSON decode keeps invalid JSON / auth payloads
  on the normal error path without `pcall`.
