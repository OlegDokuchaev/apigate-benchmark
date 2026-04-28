# gateway-python

Python implementation of the same four-route contract as
`../gateway-apigate/` (Rust) and `../gateway-kong/` (Kong OSS). Bare ASGI,
no framework, no middleware — the file you grep for a route is the file
that handles it.

Stack: Python 3.13, [Granian](https://github.com/emmett-framework/granian)
(Rust ASGI server) with [rloop](https://github.com/gi0baro/rloop) (Rust
`asyncio` event loop), [msgspec](https://github.com/jcrist/msgspec) for
JSON validation/encoding, [aiohttp](https://github.com/aio-libs/aiohttp)
for upstream HTTP, [pydantic-settings](https://github.com/pydantic/pydantic-settings)
for typed env config, `jemalloc` via `LD_PRELOAD`.

## Routes

| Method | Path             | Behavior                                                                 |
|--------|------------------|--------------------------------------------------------------------------|
| GET    | `/items`         | Bare streaming proxy — no parsing, no auth. Baseline.                    |
| GET    | `/my-items`      | `POST /verify` against auth-service, inject `x-user-id` / `x-user-email`, strip `Authorization`, proxy. |
| POST   | `/items/search`  | Validate body against `SearchInput` (`{category?: str, max_price?: int}`), forward original bytes. |
| POST   | `/items/lookup`  | Decode `{q: str}`, re-encode as internal `{query, limit, source}`, forward. |

Error envelope is always `{"error": "<message>"}`. Status codes:

- `400` — malformed JSON or schema violation on `/items/search` / `/items/lookup`.
- `401` — `/my-items` without `Authorization` or with an invalid token.
- `413` — request body exceeds `MAX_BODY_BYTES`.
- `502` — auth or data upstream returned an unexpected status / network error.
- `503` — the gateway has not finished startup yet.
- `504` — auth or data upstream timed out.

## Configuration

Defaults live in `.env.example`. In Docker, values come from compose env.

| Variable                    | Default                         | Purpose                                          |
|-----------------------------|---------------------------------|--------------------------------------------------|
| `ORIGIN_BASE_URL`           | `http://127.0.0.1:8002`         | `data-service` base URL.                         |
| `AUTH_VERIFY_URL`           | `http://127.0.0.1:8001/verify`  | Full URL of `auth-service` /verify.              |
| `MAX_BODY_BYTES`            | `1048576`                       | Buffer limit for buffered endpoints.             |
| `AIOHTTP_CONNECTOR_LIMIT`   | `0`                             | `TCPConnector` total pool limit (`0` = unlimited). |
| `AIOHTTP_LIMIT_PER_HOST`    | `512`                           | Per-host idle pool cap — bounds the FD blow-up on bursty ramps even when `AIOHTTP_CONNECTOR_LIMIT=0`. **Applies separately to each (scheme, host, port) tuple**, so `auth:8001` and `data:8002` each get their own 512-slot pool per worker. Cumulative across 4 workers = 2048 per upstream — matched with kong's `KEEPALIVE_POOL_SIZE` (auth, lua) / `KONG_UPSTREAM_KEEPALIVE_POOL_SIZE` (data, nginx) and apigate's `AUTH_POOL_MAX_IDLE_PER_HOST` / `DATA_POOL_MAX_IDLE_PER_HOST`. A single `aiohttp.ClientSession` is shared between auth and data calls; aiohttp's `limit_per_host` is the per-host cap so no second session/connector is needed for symmetry with apigate's split auth/data clients. |
| `AIOHTTP_DNS_TTL`           | `300`                           | aiohttp DNS cache TTL (s).                       |
| `AIOHTTP_KEEPALIVE_TIMEOUT` | `120.0`                         | How long aiohttp keeps idle keep-alive sockets in the pool. Aligned with `POOL_IDLE_TIMEOUT` in apigate and `KONG_UPSTREAM_KEEPALIVE_IDLE_TIMEOUT` in kong (default aiohttp 15 s is too short across k6 profile transitions). |
| `UPSTREAM_CONNECT_TIMEOUT`  | `3.0`                           | Data upstream connect (s).                       |
| `UPSTREAM_TOTAL_TIMEOUT`    | `10.0`                          | Data upstream total (s).                         |
| `AUTH_CONNECT_TIMEOUT`      | `1.0`                           | Auth upstream connect (s) — tighter than data.   |
| `AUTH_TOTAL_TIMEOUT`        | `3.0`                           | Auth upstream total (s).                         |

## Run

```bash
# native
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
./scripts/run.sh                 # → 127.0.0.1:8000

# docker
docker build -t gateway-python .
docker run --rm -p 8092:8000 --env-file .env gateway-python
```

`scripts/run.sh` picks up `GRANIAN_WORKERS` (default: `$(nproc)` / `sysctl hw.ncpu` / `1`).
The Dockerfile's `CMD` auto-scales to `$(nproc)` the same way.

## Lint / types

```bash
python -m flake8 apigate_bench
python -m mypy apigate_bench
```

## Design notes

- **ASGI dispatch is manual.** Two nested `if`s on `scope["method"]` / `scope["path"]`.
  No router, no middleware — one function call per route.
- **msgspec singletons.** `_search_decoder`, `_lookup_decoder`, `_lookup_encoder`
  are module-level, so msgspec reuses its internal scratch buffers across
  requests. Decoders are typed, so invalid bodies fail as `ValidationError`
  and become `400` without ever producing a Python dict.
- **One shared `aiohttp.ClientSession`.** Created during ASGI
  `lifespan.startup`, closed on shutdown. `limit=0` (unlimited total),
  `limit_per_host=512` (FD blow-up guard under bursts; 512 × 4 workers =
  2048 cumulative, matches kong / apigate), `keepalive_timeout=120s`
  (matches the other gateways' upstream pool idle), and `enable_cleanup_closed=True`
  reaps half-closed sockets the kernel marks under bursty ramps.
  DNS is cached.
- **Transparent-proxy flags.** `auto_decompress=False` (otherwise we would
  have to re-encode and lie about `content-encoding`/`content-length`).
  `raise_for_status=False` (upstream 4xx/5xx flow to the client verbatim).
- **Split timeouts.** The proxy path uses `sock_read=None` because the
  response body is streamed — a per-socket-read deadline would abort a
  slow-but-valid chunked body. `/verify` is single-shot, so it gets
  `sock_read=AUTH_TOTAL_TIMEOUT` to catch a stuck auth faster. `total`
  still bounds both paths.
- **Zero-copy body relay.** `_relay_response` uses `response.content.iter_any()`;
  chunks are handed to the ASGI `send` as-is. On mid-stream upstream errors,
  the body is closed with a final empty chunk — never a second
  `http.response.start`, which would violate ASGI.
- **Header handling.** ASGI 3.0 delivers header names as lowercased bytes,
  so no `.lower()` on the request path. `latin-1` is the canonical 1:1
  byte ↔ codepoint mapping that RFC 9110 allows for header values.
  Hop-by-hop headers (`connection`, `keep-alive`, …) are dropped in both
  directions.
- **jemalloc via `LD_PRELOAD`.** The aiohttp + msgspec hot path churns
  short-lived allocations; jemalloc scales past glibc ptmalloc once the
  worker count crosses ~8. Same family of fix as `mimalloc` in apigate.
- **Granian `--runtime-mode st`.** Single-threaded-per-worker runtime,
  `--workers $(nproc)` gives process-level parallelism. Matches Kong's
  `worker_processes=auto` and tokio's default multi-thread runtime.
- **Granian `--backlog 4096`.** `listen(2)` backlog passed to each
  reuseport listener. Granian additionally derives an in-flight cap
  `backpressure = backlog / workers = 1024 per worker` (≈ 4096 cumulative
  on a 4-core host) — that's the practical concurrency limit, not the
  raw accept queue size. Kernel still clamps to `net.core.somaxconn`.
