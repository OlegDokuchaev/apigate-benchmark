# gateway-apigate

Reference gateway for the apigate example. Built on
[`apigate`](https://github.com/OlegDokuchaev/apigate) 0.2.6 — a Rust API
gateway framework where routes, hooks, body validators, and payload
rewriters are declared via attribute macros and the runtime wires them into
an `axum`/`hyper` pipeline.

Stack: Rust 1.88, `apigate` 0.2.6, `tokio` multi-thread runtime, `reqwest` with
`rustls-tls`, `mimalloc` as the global allocator.

## Routes

| Method | Path             | apigate feature                                 | Behavior                                                      |
|--------|------------------|-------------------------------------------------|---------------------------------------------------------------|
| GET    | `/items`         | none — plain proxy                              | Baseline for measuring raw proxy overhead.                    |
| GET    | `/my-items`      | `before = [require_auth]`                       | Verifies Bearer, injects `x-user-id` / `x-user-email`, strips `authorization`. |
| POST   | `/items/search`  | `json = SearchInput`                            | Validates body shape, then forwards it as-is.                 |
| POST   | `/items/lookup`  | `json = LookupInput, map = remap_lookup`        | Rewrites public `{q}` into internal `{query, limit, source}`. |

The four scenarios isolate the per-feature overhead so the benchmark can
attribute latency (plain proxy vs. extra `/verify` hop vs. body
validation vs. body rewrite).

## Configuration

All via env vars. Defaults are in `.env`; compose overrides with `.env.docker`.

| Var                 | Example                  | Notes                                           |
|---------------------|--------------------------|-------------------------------------------------|
| `LISTEN_ADDR`       | `0.0.0.0:8080`           | `SocketAddr` the gateway binds to.              |
| `AUTH_BACKEND`      | `http://127.0.0.1:8001`  | Base URL of `auth-service`. `/verify` is joined once at startup. |
| `DATA_BACKEND`      | `http://127.0.0.1:8002`  | Base URL of `data-service`. Forwarded path stays verbatim. |
| `REQUEST_TIMEOUT`   | `10s`                    | Total budget for the upstream data call.        |
| `CONNECT_TIMEOUT`   | `3s`                     | TCP connect timeout for data / auth.            |
| `VERIFY_TIMEOUT`    | `3s`                     | Total budget for `POST /verify`. Sized well under `REQUEST_TIMEOUT` so auth failure does not consume the whole request budget. |
| `POOL_IDLE_TIMEOUT` | `120s`                   | How long idle upstream sockets stay in the hyper / reqwest pool. Aligned with the same setting in Kong (`KONG_UPSTREAM_KEEPALIVE_IDLE_TIMEOUT`), APISIX (`keepalive_pool.idle_timeout`), and Python (`AIOHTTP_KEEPALIVE_TIMEOUT`) so the four gateways are compared at the same pool aging. |
| `TCP_KEEPALIVE`     | `30s`                    | Socket-level TCP keepalive idle for gateway -> upstream sockets. Used by both the data `HttpConnector` and auth `reqwest` client. |
| `DATA_POOL_MAX_IDLE_PER_HOST` | `2048`         | Cap on idle hyper-util connections to `data-service`. Default in `UpstreamConfig` is `usize::MAX` (unbounded), which lets the idle pool blow up FDs under bursty ramp profiles. 2048 matches cumulative Kong/APISIX (4 workers × 512) and Python (4 workers × 512) capacity, so the four gateways enter ramp burst with the same upstream-pool budget. Requires `apigate ≥ 0.2.5` (`UpstreamConfig::pool_max_idle_per_host`) and host `ulimit -n ≥ 65536` so the single tokio process can hold 2048 idle + inbound + inflight FDs without hitting ENOBUFS. |
| `AUTH_POOL_MAX_IDLE_PER_HOST` | `2048`         | Cap on idle reqwest connections to `auth-service`. Critical under ramp on `/my-items`: when `auth-service` slows under load, in-flight `/verify` calls accumulate beyond the pool, which then opens fresh TCP per excess request and closes them on the way back (TIME_WAIT churn) — that's what pushed apigate's `/my-items` ramp p99 over 1 s before reaching peak in earlier benchmark generations. 2048 matches Kong/APISIX per-worker × 4 (`keepalive_pool=512` passed from their declarative YAML) and Python's `AIOHTTP_LIMIT_PER_HOST × 4`. |
| `LISTEN_BACKLOG`    | `4096`                   | `listen(2)` backlog passed to `apigate::ServeConfig::backlog`. Matches cumulative reuseport capacity of Kong / APISIX / Python on a 4-core host. Kernel still clamps to `net.core.somaxconn` — raise that on the host too. Requires `apigate ≥ 0.2.6` (`ServeConfig`/`run_with`). |

Timeouts use [`humantime`](https://docs.rs/humantime) syntax (`10s`, `500ms`).

## Run

```bash
# native — picks up .env via your shell, e.g. `set -a; source .env; set +a`
cargo run --release

# docker
docker build -t gateway-apigate .
docker run --rm -p 8080:8080 --env-file .env gateway-apigate
```

Compose from the repo root brings this up alongside `auth-service`,
`data-service`, and the other gateways.

## Design notes

- **mimalloc.** Set as `#[global_allocator]`. The request hot path allocates
  header maps, body buffers, and serde-owned strings; glibc ptmalloc
  scales poorly on that pattern past ~8 workers. mimalloc is drop-in and
  gives 5–15 % on soak runs.
- **tokio defaults.** `#[tokio::main]` uses a multi-thread runtime sized to
  `available_parallelism()`. Not tuned further — apigate / axum / hyper
  schedule fine on the default worker pool.
- **`require_auth` hook.** Pulls the `Authorization` header, calls
  `AuthClient::verify`, writes `x-user-id` / `x-user-email`, and removes the
  original `Authorization` so the JWT never reaches `data-service`. A single
  `String` allocation for the token is unavoidable — we need an owned copy
  before the async `verify` call so the `&mut ctx` borrow can be released.
- **`remap_lookup` map.** `#[apigate::map]` requires an owned return, so
  `query` has to be a `String` rather than `&str`/`Cow`. `input.q.trim().to_string()`
  is the single allocation per lookup request.
- **`AuthClient` tuning.**
  - `verify_url` is parsed into a `reqwest::Url` once; reqwest's `IntoUrl`
    otherwise re-parses on every `.post()`.
  - `.no_proxy()` disables `HTTP(S)_PROXY` autodetection — all traffic is
    internal and must not be routed through a caller's proxy env.
  - `tcp_nodelay(true)` disables Nagle on the auth hop — `/verify` payloads
    are small (~150 B request, ~80 B reply), Nagle's 40 ms cork would
    dominate latency.
  - `http1_only()` pins the wire version. auth-service is Go fasthttp,
    HTTP/1.1 only — pinning skips ALPN negotiation on every connect.
  - `pool_idle_timeout(POOL_IDLE_TIMEOUT)` and `pool_max_idle_per_host(AUTH_POOL_MAX_IDLE_PER_HOST)`
    keep a hot pool under bursty ramps so the gateway doesn't open a fresh
    TCP connection (and burn an ephemeral port → TIME_WAIT) per request.
    The default 2048 matches cumulative auth-pool capacity in Kong/APISIX
    (4 × `keepalive_pool=512` from `kong.yml` / `apisix.yaml`) and Python
    (4 × `AIOHTTP_LIMIT_PER_HOST=512`).
  - All errors (network, non-2xx, bad JSON) collapse to `unauthorized` so
    upstream details never leak into the response.
- **Listen backlog.** Bound at startup via
  `apigate::run_with(addr, app, ServeConfig::new().backlog(LISTEN_BACKLOG).tcp_nodelay(true))`.
  The default OS backlog (128 on older Linux) overflows under k6
  ramping-arrival-rate workloads, surfacing as ~1 % of requests hanging
  for the full client-side timeout (bimodal latency). 4096 absorbs typical
  ramp bursts; kernel still clamps to `net.core.somaxconn`.
- **Inbound `TCP_NODELAY`.** `ServeConfig::tcp_nodelay(true)` sets the flag
  on every accepted client socket via axum's `ListenerExt::tap_io`. The
  default on accepted streams is *off* — the four routes carry small JSON
  (~80–150 B), Nagle's 40 ms cork would dominate latency. The upstream
  side (gateway → data) already has `TCP_NODELAY` from `UpstreamConfig`'s
  default.
- **Inbound HTTP keep-alive.** axum/hyper keeps HTTP/1.1 client connections
  persistent by default; `ServeConfig` does not expose a request-count or idle
  timeout knob, so there is no additional apigate-side value to set here.
- **Bounded upstream idle pool.** `UpstreamConfig::pool_max_idle_per_host(2048)`.
  Default is `usize::MAX` — under k6 ramping the idle pool would grow
  without bound (FD blow-up + GC churn). 2048 mirrors what cumulative
  reuseport capacity gives Kong/APISIX (4 × 512) and Python (4 × 512) on
  the same host. With `ulimit -n=65536` (see root README's "Host requirements")
  the single tokio process holds up to 2048 idle data + 2048 idle auth +
  inbound / in-flight sockets — well under the limit.
- **Upstream TCP keepalive.** `TCP_KEEPALIVE` from `.env` is applied through
  `UpstreamConfig::configure_connector` / `HttpConnector::set_keepalive(...)`
  on data sockets; `AuthClient` receives the same config value for reqwest
  auth-service sockets. HTTP keep-alive pool idle remains configured separately
  at 120s across all gateways.
- **Release profile.** `lto = "thin"`, `codegen-units = 1`, `strip = true` —
  standard Rust perf flags.
