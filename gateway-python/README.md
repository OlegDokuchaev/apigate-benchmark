# gateway-python

Bare ASGI gateway using Granian, rloop, msgspec, aiohttp, pydantic-settings, and jemalloc.

## Routes

| Method | Path | Implementation |
|---|---|---|
| `GET` | `/items` | stream proxy |
| `GET` | `/my-items` | auth verify, inject identity headers, proxy |
| `POST` | `/items/search` | msgspec validation, forward original body |
| `POST` | `/items/lookup` | msgspec validation, rewrite body |

Auth failures collapse to `401`, matching apigate/Kong/APISIX.

## Config

Defaults are in `.env.example`; compose overrides upstream URLs.

| Env | Default | Purpose |
|---|---:|---|
| `ORIGIN_BASE_URL` | `http://127.0.0.1:8002` | data upstream |
| `AUTH_VERIFY_URL` | `http://127.0.0.1:8001/verify` | auth verify URL |
| `AIOHTTP_CONNECTOR_LIMIT` | `0` | total connector limit, `0` means unlimited |
| `AIOHTTP_LIMIT_PER_HOST` | `512` | per-worker per-upstream idle pool |
| `AIOHTTP_DNS_TTL` | `300` | DNS cache seconds |
| `AIOHTTP_KEEPALIVE_TIMEOUT` | `120.0` | upstream pool idle |
| `AIOHTTP_TCP_KEEPALIVE_IDLE` | `30` | socket TCP keepalive idle |
| `GRANIAN_HTTP1_KEEP_ALIVE` | `true` | enables inbound HTTP/1.1 keepalive |
| `UPSTREAM_CONNECT_TIMEOUT` | `3.0` | data connect timeout |
| `UPSTREAM_TOTAL_TIMEOUT` | `10.0` | data total timeout |
| `AUTH_CONNECT_TIMEOUT` | `3.0` | auth connect timeout |
| `AUTH_TOTAL_TIMEOUT` | `3.0` | auth total timeout |

On a 4-vCPU host, `512 x 4 = 2048` upstream idle slots per upstream.

## Fairness Notes

| Area | Value |
|---|---|
| workers | `--workers $(nproc)` |
| runtime | `--runtime-mode st --loop rloop` |
| backlog | `4096` |
| inbound keepalive | controlled by `GRANIAN_HTTP1_KEEP_ALIVE` |
| upstream keepalive | aiohttp connector, 120s idle |
| TCP keepalive | aiohttp socket factory, 30s idle where OS supports it |
| allocator | jemalloc |

## Run

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
./scripts/run.sh
```

With compose:

```bash
docker compose up --build gateway-python
```

## Check

```bash
python3 -m py_compile gateway-python/apigate_bench/*.py
```
