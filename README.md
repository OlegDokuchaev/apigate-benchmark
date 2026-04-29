# apigate-benchmark

Head-to-head benchmark of the [apigate](https://github.com/OlegDokuchaev/apigate)
Rust gateway library against Kong OSS, Apache APISIX, and a hand-rolled Python ASGI gateway.
All four implementations expose the same four-route contract over the same
pair of backends — `auth-service` and `data-service` — so the numbers
measure the gateway, not the surrounding code. Driven by a k6 matrix.

- **gateway-apigate** — Rust on [apigate](https://github.com/OlegDokuchaev/apigate) 0.2.6 (subject of the benchmark).
- **gateway-kong** — Kong OSS 3.7 in DB-less mode, logic in a `pre-function` Lua plugin.
- **gateway-apisix** — Apache APISIX 3.16 in standalone mode, logic in a `serverless-pre-function` Lua plugin.
- **gateway-python** — Granian + rloop + msgspec + aiohttp on bare ASGI.

JWT verification happens in the gateway via `POST /verify`; `data-service`
knows nothing about tokens — it only sees `x-user-id` / `x-user-email`
headers the gateway injects after a successful verification.

```
                ┌────────────────────┐ :8080
client ──JWT──▶ │ gateway-apigate    │ ───┐
                └────────────────────┘    │
                ┌────────────────────┐    │   ┌─────────────┐
        ──────▶ │ gateway-kong       │ ───┼──▶│ data-service│ :8002
                └────────────────────┘ :8090  │  Go fasthttp│
                ┌────────────────────┐    │   └─────────────┘
        ──────▶ │ gateway-apisix     │ ───┤         ▲
                └────────────────────┘ :8093        │ x-user-id
                ┌────────────────────┐    │         │
        ──────▶ │ gateway-python     │ ───┘         │
                └────────────────────┘ :8092        │
                          │                         │
                          │ POST /verify    ┌─────────────┐
                          └────────────────▶│ auth-service│ :8001
                                            │  Go fasthttp│
                                            └─────────────┘
```

## Layout

| Directory                                        | Stack                                        | Port         | Role                                         |
|--------------------------------------------------|----------------------------------------------|--------------|----------------------------------------------|
| [`auth-service/`](auth-service/README.md)        | Go, fasthttp + JWT HS256 + bcrypt            | 8001         | `/register`, `/login`, `/verify` (token → id) |
| [`data-service/`](data-service/README.md)        | Go, fasthttp                                 | 8002         | Product catalogue; trusts `x-user-id`        |
| [`gateway-apigate/`](gateway-apigate/README.md)  | Rust, apigate 0.2.6                          | 8080         | Reverse proxy with `before` hook, `json`, `map` |
| [`gateway-kong/`](gateway-kong/README.md)        | Kong 3.7 (DB-less) + Lua (`pre-function`)    | 8090 / 8091  | Same contract via Kong declarative config    |
| [`gateway-apisix/`](gateway-apisix/README.md)    | Apache APISIX 3.16 standalone + Lua (`serverless-pre-function`) | 8093 | Same contract via APISIX declarative config |
| [`gateway-python/`](gateway-python/README.md)    | Granian + rloop + msgspec + aiohttp (ASGI)   | 8092         | Same contract on bare Python ASGI            |

Per-implementation details live in the `README.md` of each directory.

## Public contract

All four gateways expose the same routes against `data-service`:

| Method | Path             | Gateway behavior                                                                 |
|--------|------------------|----------------------------------------------------------------------------------|
| GET    | `/items`         | Straight proxy — baseline, no hooks.                                             |
| GET    | `/my-items`      | Calls `/verify`, injects `x-user-id`/`x-user-email`, strips `Authorization`.     |
| POST   | `/items/search`  | Validates body `{category?: string, max_price?: int}` → forwards as-is.          |
| POST   | `/items/lookup`  | Decodes `{q: string}` → re-encodes as `{query, limit, source}` → forwards.       |

## Run with docker compose

```bash
docker compose up --build
```

Brings everything up: `auth:8001`, `data:8002`,
`gateway-apigate:8080`, `gateway-kong:8090` (admin `:8091`),
`gateway-apisix:8093`, `gateway-python:8092`, `cadvisor:8099`
(container metrics, used by the load-test harness).

## Local run (without Docker)

```bash
# 1) auth-service  (Go)
cd auth-service && go run .

# 2) data-service  (Go)
cd data-service && go run .

# 3a) gateway-apigate  (Rust)
cd gateway-apigate && cargo run --release

# 3b) gateway-kong     (Kong OSS — only via Docker)
docker compose up --build gateway-kong

# 3c) gateway-apisix   (Apache APISIX — only via Docker)
docker compose up --build gateway-apisix

# 3d) gateway-python   (Granian)
cd gateway-python
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
./scripts/run.sh
```

## Example usage

Pick the port of the gateway you want: `8080` (apigate), `8090` (kong), `8093` (apisix), `8092` (python).
Register and log in directly against `auth-service`; the catalogue is the
only thing routed through the gateway.

```bash
GW=http://localhost:8080        # or :8090 / :8093 / :8092
AUTH=http://localhost:8001

# register + log in directly against auth-service
curl -s -X POST $AUTH/register \
  -H 'content-type: application/json' \
  -d '{"email":"alice@example.com","password":"hunter22"}'

TOKEN=$(curl -s -X POST $AUTH/login \
  -H 'content-type: application/json' \
  -d '{"email":"alice@example.com","password":"hunter22"}' \
  | python3 -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')

# 1) baseline — full catalogue, no auth
curl -s $GW/items

# 2) auth hook — verify → x-user-id
curl -s $GW/my-items -H "Authorization: Bearer $TOKEN"

# 3) body validation
curl -s -X POST $GW/items/search \
  -H 'content-type: application/json' \
  -d '{"category":"office","max_price":300}'

# 4) body rewrite (public {q} → internal schema)
curl -s -X POST $GW/items/lookup \
  -H 'content-type: application/json' \
  -d '{"q":"pen"}'

# without a token, /my-items → 401
curl -i $GW/my-items
```

## How authentication works

1. The client logs in against `auth-service` → receives a JWT.
2. The protected `/my-items` route is called with `Authorization: Bearer <jwt>`.
3. The gateway:
   - issues `POST http://auth:8001/verify`;
   - from the `{user_id, email}` response, sets `x-user-id` / `x-user-email` headers;
   - strips `Authorization` so the token never reaches the upstream.
4. `data-service` only reads `x-user-id`. It knows nothing about JWTs or `auth-service`.

Where the hook lives:

| Gateway          | File                                                                           |
|------------------|--------------------------------------------------------------------------------|
| gateway-apigate  | `gateway-apigate/src/hooks.rs::require_auth`                                   |
| gateway-kong     | `gateway-kong/lua/require_auth.lua`                                            |
| gateway-apisix   | `gateway-apisix/lua/require_auth.lua`                                          |
| gateway-python   | `gateway-python/apigate_bench/auth_client.py` + `gateway.py::handle_my_items`  |

## Configuration

Key gateway env vars:

| Gateway          | Var                                       | Purpose                                         |
|------------------|-------------------------------------------|-------------------------------------------------|
| gateway-apigate  | `LISTEN_ADDR`, `AUTH_BACKEND`, `DATA_BACKEND` | URLs of auth / data upstreams                |
| gateway-apigate  | `REQUEST_TIMEOUT`, `CONNECT_TIMEOUT`, `VERIFY_TIMEOUT` | `humantime`, e.g. `3s` / `10s`      |
| gateway-kong     | `KONG_DECLARATIVE_CONFIG`, `KONG_PROXY_LISTEN` | consumed by Kong itself; config in `kong.yml` |
| gateway-kong     | `KONG_UPSTREAM_KEEPALIVE_POOL_SIZE`, `KONG_PROXY_ACCESS_LOG`, `KONG_UNTRUSTED_LUA_SANDBOX_REQUIRES` | upstream pool tuning / access log off / modules whitelisted in the `pre-function` sandbox |
| gateway-apisix   | `APISIX_STAND_ALONE`                    | file-driven standalone mode; config in `apisix.yaml` |
| gateway-apisix   | `config.yaml`, `apisix.yaml`             | listen/nginx tuning plus routes/upstream/plugin config |
| gateway-python   | `ORIGIN_BASE_URL`, `AUTH_VERIFY_URL`      | upstream entry points                           |
| gateway-python   | `UPSTREAM_*_TIMEOUT`, `AUTH_*_TIMEOUT`    | seconds; auth gets its own tighter budget       |

Defaults live in each service's `.env` / `.env.example` or gateway config files.

## Performance and concurrency

All four gateways are tuned the same "production-style" way — so the
benchmark compares **implementations**, not runtime defaults:

- **CPU auto-scaling.** tokio (apigate), nginx/Kong, nginx/APISIX, and granian (python)
  all scale workers with core count: tokio — `multi_thread` runtime with
  `available_parallelism()`; Kong / APISIX — `worker_processes=auto`;
  granian — `--workers $(nproc)` via the shell `CMD` in `gateway-python/Dockerfile`.
- **Production allocator.** apigate is built with `mimalloc` as
  `#[global_allocator]`; python, kong, and apisix run `jemalloc` via `LD_PRELOAD`
  (see each Dockerfile). The default glibc `ptmalloc` scales poorly on
  the hot path once worker count crosses ~14; mimalloc/jemalloc win
  5–15 % and stay more stable under soak load.

### Tuning matrix

The settings below are kept aligned across all four implementations so
the benchmark compares the gateway code, not the surrounding configuration.
Numbers assume a 4 vCPU host; per-worker columns are multiplied by 4 in
the cumulative-capacity column where the runtime uses SO_REUSEPORT.

| Aspect                       | apigate                                         | kong                                                  | apisix                                                | python (granian)                                      |
|------------------------------|-------------------------------------------------|-------------------------------------------------------|-------------------------------------------------------|-------------------------------------------------------|
| Workers                      | 4 (tokio multi-thread, `available_parallelism()`) | 4 (`worker_processes auto`)                          | 4 (`worker_processes auto`)                           | 4 (`--workers $(nproc)`)                              |
| Threading model              | shared async runtime, work-stealing             | per-worker event loop                                 | per-worker event loop                                 | per-worker single-thread (`--runtime-mode st`)        |
| Allocator                    | mimalloc                                        | jemalloc (`LD_PRELOAD`)                               | jemalloc (`LD_PRELOAD`)                               | jemalloc (`LD_PRELOAD`)                               |
| **Listen backlog**           | 4096 (single queue, no SO_REUSEPORT)            | 1024 per worker x 4 = **4096 cumulative** (`reuseport`) | 1024 per worker x 4 = **4096 cumulative** (`reuseport`) | `--backlog 4096` per reuseport listener x 4 = 16384 cumulative listen capacity |
| **Effective in-flight cap**  | FD-bound (no app-level cap)                     | `worker_connections=16384` per worker                 | `worker_connections=16384` per worker                 | granian `backpressure = backlog/workers = 1024` per worker -> **4096 cumulative** |
| Inbound HTTP keep-alive      | HTTP/1.1 persistent by axum/hyper default       | 120 s / 1000000 requests (`KONG_NGINX_HTTP_KEEPALIVE_*`) | 120 s / 1000000 requests (`nginx_config.http.keepalive_*`) | enabled via `GRANIAN_HTTP1_KEEP_ALIVE=true`           |
| Inbound TCP_NODELAY          | yes (`ServeConfig::tcp_nodelay(true)`)          | nginx default `tcp_nodelay on`                        | nginx default `tcp_nodelay on`                        | granian default                                       |
| **Upstream pool idle**       | 120 s (`pool_idle_timeout`)                     | 120 s (`KONG_UPSTREAM_KEEPALIVE_IDLE_TIMEOUT`)        | 120 s (`keepalive_pool.idle_timeout`)                 | 120 s (`AIOHTTP_KEEPALIVE_TIMEOUT`)                   |
| Upstream keep-alive requests | no request-count cap                            | 1000000 (`KONG_UPSTREAM_KEEPALIVE_MAX_REQUESTS`)      | 1000000 (`keepalive_pool.requests`)                   | no request-count cap                                  |
| Upstream TCP keepalive       | 30 s (`TCP_KEEPALIVE`)                          | enabled (`proxy_socket_keepalive`) + `tcp_keepalive_time=30` | enabled (`proxy_socket_keepalive`) + `tcp_keepalive_time=30` | 30 s (`AIOHTTP_TCP_KEEPALIVE_IDLE`)                  |
| Upstream pool size (per worker / cumulative) | 2048 (proxy, single shared pool) / 2048 (auth_client) | 512 / 4 x 512 = 2048             | 512 / 4 x 512 = 2048                                  | 512 (`limit_per_host`) / 4 x 512 = 2048            |
| Upstream connect timeout     | 3 s (proxy) / 3 s (auth)                        | 3 s (`connect_timeout` in `kong.yml`)                 | 3 s (`timeout.connect` / Lua auth timeout)            | 3 s (`UPSTREAM_CONNECT_TIMEOUT`) / 3 s (`AUTH_CONNECT_TIMEOUT`) |
| Upstream total timeout       | 10 s (proxy) / 3 s (auth)                       | 10 s (`read_timeout` / `write_timeout`)               | 10 s (`timeout.read` / `timeout.send`) / 3 s auth     | 10 s / 3 s                                             |
| Upstream HTTP version        | HTTP/1.1 only                                   | HTTP/1.1 (`protocol: http`)                           | HTTP/1.1 (`scheme: http`)                             | HTTP/1.1 (aiohttp default)                            |
| Upstream TCP_NODELAY         | yes (`set_nodelay(true)` on client)             | yes (`KONG_NGINX_PROXY_TCP_NODELAY=on`)               | nginx default                                         | aiohttp default                                       |

Backend services (`auth-service`, `data-service`) are aligned too:
`fasthttp.Server { ReadTimeout: 10s, WriteTimeout: 10s, IdleTimeout: 120s,
TCPKeepalive: true, TCPKeepalivePeriod: 30s }` — `IdleTimeout: 120s`
matches every gateway's upstream pool idle timeout so neither side closes
keep-alive sockets first.

The intentional asymmetry is **how concurrent in-flight requests are
capped** — apigate has a single 4096-slot accept queue and no app-level
cap; kong and apisix reuseport and limit per-worker; granian reuseports and
additionally throttles in-flight via `backpressure`. The numbers in the
matrix are picked so that **effective concurrency ≈ 4096** under burst
load in all four cases — equal real capacity rather than equal config
numbers.

### Host requirements

The matrix above (cumulative pool 2048 per upstream, listen backlog 4096,
`worker_connections 16384` on Kong/APISIX) is calibrated for a 4 vCPU / ≥ 8 GiB
Linux benchmark host. Three host-level knobs **must** be set, otherwise
the kernel silently clamps every gateway's tuning down and the comparison
becomes meaningless.

#### File descriptors — `ulimit -n ≥ 65536`

Every concurrent upstream socket, every inbound k6 connection, every
keep-alive idle slot — all share one per-process FD table. apigate is
the binding case: a single tokio process holds ~2048 idle data + 256 idle
auth + a few hundred in-flight + a few hundred inbound under steady state,
and k6's `RAMP_MAX_VUS=6000` can briefly multiply inbound at the saturation
point. The default soft limit on most distros is 1024 — apigate hits
`EMFILE` (gateway returns 502s) well before reaching real saturation.

`docker-compose.yml` already pins `ulimits.nofile = 65536` on every
gateway service. For native runs (`cargo run --release`,
`./scripts/run.sh`, etc.) raise the host-level limit too:

```bash
# /etc/security/limits.d/99-bench.conf
*  soft  nofile  65536
*  hard  nofile  65536
# applies on next login; verify with `ulimit -n`
```

Kong/granian split FDs across 4 worker processes, so each worker's budget
is 4× smaller — 65536 is overkill for them but harmless.

#### Listen backlog — `net.core.somaxconn ≥ 8192`

apigate sets `LISTEN_BACKLOG=4096`, granian gets `--backlog 4096`, Kong
declares `backlog=1024 reuseport` x 4 = 4096 cumulative, and APISIX
declares the same `backlog=1024` + `enable_reuseport`. The kernel
clamps **every** `listen()` call to `somaxconn` regardless of what the
application requests — if it stays at 128/4096, the configuration above
is silently truncated. Set 8192 to leave a clear margin over the highest
configured backlog.

#### Ephemeral ports + TIME_WAIT — gateway → upstream egress

The gateway opens new TCP connections to `auth:8001` / `data:8002` whenever
the keep-alive pool is exhausted. Each closed connection sits in
`TIME_WAIT` for ~60 s, holding an ephemeral port. Under a 5-minute ramp at
10k RPS the gateway can burn through the default port range
(`32768–60999`, ~28 k ports) faster than they free. Symptom: bimodal
latency tail and `EADDRNOTAVAIL` in gateway logs.

#### Recommended sysctl set

```bash
sudo tee /etc/sysctl.d/99-bench.conf <<'EOF'
# Listen backlog cap. Must be ≥ the highest LISTEN_BACKLOG /
# KONG_PROXY_LISTEN backlog / granian --backlog used in this repo.
net.core.somaxconn = 8192

# Half-open SYN queue. Default 1024 is tight under k6 ramping bursts.
net.ipv4.tcp_max_syn_backlog = 8192

# Per-CPU softirq packet backlog. Default 1000; raise for sustained 10k RPS.
net.core.netdev_max_backlog = 5000

# Egress port pool. Default 32768–60999 gives ~28k ports; 10000–65535 ≈ 55k.
net.ipv4.ip_local_port_range = 10000 65535

# Reuse TIME_WAIT sockets for new outgoing connections. Safe on a private
# benchmark network; revisit on internet-facing hosts.
net.ipv4.tcp_tw_reuse = 1
EOF
sudo sysctl --system
```

Verify after applying: `sysctl net.core.somaxconn net.ipv4.ip_local_port_range`.

#### Quick sanity check before running the matrix

```bash
ulimit -n                              # ≥ 65536
sysctl net.core.somaxconn              # ≥ 8192
docker compose ps                      # one gateway up at a time
docker compose exec gateway-apigate sh -c 'ulimit -n'  # ≥ 65536 inside container
```

### Kong / APISIX-specific notes

Beyond the shared tuning above, the Kong service in `docker-compose.yml`
also disables access log (`KONG_PROXY_ACCESS_LOG=off`), whitelists
`require_auth` / `transforms` as the only modules the Lua `pre-function`
sandbox may `require()` (`KONG_UNTRUSTED_LUA_SANDBOX_REQUIRES`), and
keeps both inbound and upstream keep-alive request caps at 1000000 so a
single persistent socket is not aged-out during the matrix on request-count grounds.

APISIX mirrors the same values in `gateway-apisix/config.yaml` and
`gateway-apisix/apisix.yaml`: standalone YAML provider, access log off,
`worker_connections=16384`, `backlog=1024` with `enable_reuseport`, upstream
`keepalive_pool.size=512`, `idle_timeout=120`, `requests=1000000`, inbound
nginx `keepalive_timeout=120s` / `keepalive_requests=1000000`, and
`proxy_socket_keepalive on` for upstream proxy sockets. Compose pins
`net.ipv4.tcp_keepalive_time=30` on every gateway container so nginx's
SO_KEEPALIVE timing matches apigate and python.

## Load testing

[`load-tests/`](load-tests/README.md) contains a k6 matrix for a fair
head-to-head:

- **3 profiles × 4 routes = 12 runs per gateway.**
- Profiles: `steady` (constant-arrival-rate, 2500 RPS × 2 min),
  `ramp` (0 → 20000 RPS over 5 min), `stress` (10000 RPS × 1 min).
- All **open-model** (`constant-arrival-rate` / `ramping-arrival-rate`):
  RPS is pinned, so latency reflects gateway state rather than VU-pool
  saturation.
- Per-container CPU / memory / network are pulled from
  [cAdvisor](https://github.com/google/cadvisor) after each run — see
  [`load-tests/README.md`](load-tests/README.md).

Latest matrix run on 4 vCPU / 10 GiB Linux is summarised in
[`load-tests/RESULTS.md`](load-tests/RESULTS.md). Headline (steady, 2500 RPS):
apigate p99 1.3–3.6 ms / 34–57 % CPU / 70 MiB; kong 2.5–10 ms / 45–82 % CPU / 530 MiB;
python 9–104 ms / 104–163 % CPU / 200 MiB. That historical run predates
`gateway-apisix`; rerun the matrix to add APISIX rows. See `RESULTS.md`
for ramp and stress.

Run one gateway at a time — stop the others so they don't share CPU:

```bash
docker compose up -d auth data gateway-apigate cadvisor

./load-tests/run.sh apigate http://localhost:8080

docker compose stop gateway-apigate
docker compose up -d gateway-apisix
./load-tests/run.sh apisix http://localhost:8093
# -> load-tests/results/<gateway>_<route>_<profile>.json            (k6 summary)
# -> load-tests/results/<gateway>_<route>_<profile>_resources.json  (cAdvisor CPU/mem aggregates)
```

RPS defaults are overridable via env:
`STEADY_RPS=800 STRESS_RPS=4000 ./load-tests/run.sh apigate http://localhost:8080`.
The full list (including `COOLDOWN` between runs and `*_OVERRIDE` for
matrix subsets) is in [`load-tests/README.md`](load-tests/README.md).

## License

MIT. See [`LICENSE`](LICENSE).
