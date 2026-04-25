# apigate-benchmark

Head-to-head benchmark of the [apigate](https://github.com/OlegDokuchaev/apigate)
Rust gateway library against Kong OSS and a hand-rolled Python ASGI gateway.
All three implementations expose the same four-route contract over the same
pair of backends — `auth-service` and `data-service` — so the numbers
measure the gateway, not the surrounding code. Driven by a k6 matrix.

- **gateway-apigate** — Rust on [apigate](https://github.com/OlegDokuchaev/apigate) 0.2.4 (subject of the benchmark).
- **gateway-kong** — Kong OSS 3.7 in DB-less mode, logic in a `pre-function` Lua plugin.
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
        ──────▶ │ gateway-python     │ ───┘         ▲
                └────────────────────┘ :8092        │ x-user-id
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
| [`gateway-apigate/`](gateway-apigate/README.md)  | Rust, apigate 0.2.4                          | 8080         | Reverse proxy with `before` hook, `json`, `map` |
| [`gateway-kong/`](gateway-kong/README.md)        | Kong 3.7 (DB-less) + Lua (`pre-function`)    | 8090 / 8091  | Same contract via Kong declarative config    |
| [`gateway-python/`](gateway-python/README.md)    | Granian + rloop + msgspec + aiohttp (ASGI)   | 8092         | Same contract on bare Python ASGI            |

Per-implementation details live in the `README.md` of each directory.

## Public contract

All three gateways expose the same routes against `data-service`:

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
`gateway-python:8092`, `cadvisor:8099` (container metrics, used by the
load-test harness).

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

# 3c) gateway-python   (Granian)
cd gateway-python
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
./scripts/run.sh
```

## Example usage

Pick the port of the gateway you want: `8080` (apigate), `8090` (kong), `8092` (python).
Register and log in directly against `auth-service`; the catalogue is the
only thing routed through the gateway.

```bash
GW=http://localhost:8080        # or :8090 / :8092
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
| gateway-python   | `gateway-python/apigate_bench/auth_client.py` + `gateway.py::handle_my_items`  |

## Configuration

Key gateway env vars:

| Gateway          | Var                                       | Purpose                                         |
|------------------|-------------------------------------------|-------------------------------------------------|
| gateway-apigate  | `LISTEN_ADDR`, `AUTH_BACKEND`, `DATA_BACKEND` | URLs of auth / data upstreams                |
| gateway-apigate  | `REQUEST_TIMEOUT`, `CONNECT_TIMEOUT`, `VERIFY_TIMEOUT` | `humantime`, e.g. `3s` / `10s`      |
| gateway-kong     | `KONG_DECLARATIVE_CONFIG`, `KONG_PROXY_LISTEN` | consumed by Kong itself; config in `kong.yml` |
| gateway-kong     | `KONG_UPSTREAM_KEEPALIVE_POOL_SIZE`, `KONG_PROXY_ACCESS_LOG`, `KONG_UNTRUSTED_LUA_SANDBOX_REQUIRES` | upstream pool tuning / access log off / modules whitelisted in the `pre-function` sandbox |
| gateway-python   | `ORIGIN_BASE_URL`, `AUTH_VERIFY_URL`      | upstream entry points                           |
| gateway-python   | `UPSTREAM_*_TIMEOUT`, `AUTH_*_TIMEOUT`    | seconds; auth gets its own tighter budget       |

Defaults live in each service's `.env` / `.env.example`.

## Performance and concurrency

All three gateways are tuned the same "production-style" way — so the
benchmark compares **implementations**, not runtime defaults:

- **CPU auto-scaling.** tokio (apigate), nginx/Kong, and granian (python)
  all scale workers with core count: tokio — `multi_thread` runtime with
  `available_parallelism()`; Kong — `worker_processes=auto`; granian —
  `--workers $(nproc)` via the shell `CMD` in `gateway-python/Dockerfile`.
- **Production allocator.** apigate is built with `mimalloc` as
  `#[global_allocator]`; python and kong run `jemalloc` via `LD_PRELOAD`
  (see each Dockerfile). The default glibc `ptmalloc` scales poorly on
  the hot path once worker count crosses ~14; mimalloc/jemalloc win
  5–15 % and stay more stable under soak load.
- **Kong tuning in compose.** Access log off, upstream-keepalive pool
  raised to 512, `require_auth` / `transforms` whitelisted as the only
  modules the Lua `pre-function` sandbox may `require()`.

## Load testing

[`load-tests/`](load-tests/README.md) contains a k6 matrix for a fair
head-to-head:

- **3 profiles × 4 routes = 12 runs per gateway.**
- Profiles: `steady` (constant-arrival-rate, 500 RPS × 2 min),
  `ramp` (0 → 2000 RPS over 5 min), `stress` (2500 RPS × 1 min).
- All **open-model** (`constant-arrival-rate` / `ramping-arrival-rate`):
  RPS is pinned, so latency reflects gateway state rather than VU-pool
  saturation.
- Per-container CPU / memory / network are pulled from
  [cAdvisor](https://github.com/google/cadvisor) after each run — see
  [`load-tests/README.md`](load-tests/README.md).

Run one gateway at a time — stop the others so they don't share CPU:

```bash
docker compose up -d auth data gateway-apigate cadvisor

./load-tests/run.sh apigate http://localhost:8080
# -> load-tests/results/<gateway>_<route>_<profile>.json            (k6 summary)
# -> load-tests/results/<gateway>_<route>_<profile>_resources.json  (cAdvisor CPU/mem aggregates)
```

RPS defaults are overridable via env:
`STEADY_RPS=800 STRESS_RPS=4000 ./load-tests/run.sh apigate http://localhost:8080`.
The full list (including `COOLDOWN` between runs and `*_OVERRIDE` for
matrix subsets) is in [`load-tests/README.md`](load-tests/README.md).

## License

MIT. See [`LICENSE`](LICENSE).
