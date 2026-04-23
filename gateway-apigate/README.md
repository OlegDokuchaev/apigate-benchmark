# gateway-apigate

Reference gateway for the apigate example. Built on
[`apigate`](https://github.com/OlegDokuchaev/apigate) 0.2.4 — a Rust API
gateway framework where routes, hooks, body validators, and payload
rewriters are declared via attribute macros and the runtime wires them into
an `axum`/`hyper` pipeline.

Stack: Rust 1.88, `apigate` 0.2.4, `tokio` multi-thread runtime, `reqwest` with
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

| Var               | Example                  | Notes                                           |
|-------------------|--------------------------|-------------------------------------------------|
| `LISTEN_ADDR`     | `0.0.0.0:8080`           | `SocketAddr` the gateway binds to.              |
| `AUTH_BACKEND`    | `http://127.0.0.1:8001`  | Base URL of `auth-service`. `/verify` is joined once at startup. |
| `DATA_BACKEND`    | `http://127.0.0.1:8002`  | Base URL of `data-service`. Forwarded path stays verbatim. |
| `REQUEST_TIMEOUT` | `10s`                    | Total budget for the upstream data call.        |
| `CONNECT_TIMEOUT` | `3s`                     | TCP connect timeout for data / auth.            |
| `VERIFY_TIMEOUT`  | `3s`                     | Total budget for `POST /verify`. Sized well under `REQUEST_TIMEOUT` so auth failure does not consume the whole request budget. |

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
  - `tcp_keepalive(15s)` keeps pooled sockets alive across k6 profile
    pauses; without it the next wave pays a full TCP handshake per upstream.
  - All errors (network, non-2xx, bad JSON) collapse to `unauthorized` so
    upstream details never leak into the response.
- **Release profile.** `lto = "thin"`, `codegen-units = 1`, `strip = true` —
  standard Rust perf flags.
