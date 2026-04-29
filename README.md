# apigate-benchmark

Benchmark of four gateway implementations over the same Go backends:

| Component | Port | Purpose |
|---|---:|---|
| `auth-service` | 8001 | `/register`, `/login`, `/verify` |
| `data-service` | 8002 | catalogue API |
| `gateway-apigate` | 8080 | Rust `apigate` reference gateway |
| `gateway-kong` | 8090 | Kong 3.7 DB-less + Lua |
| `gateway-apisix` | 8093 | Apache APISIX 3.16 standalone + Lua |
| `gateway-python` | 8092 | Granian/rloop/msgspec/aiohttp ASGI gateway |
| `cadvisor` | 8099 | load-test resource sampling |

All gateways expose the same public contract:

| Method | Path | Work done in gateway |
|---|---|---|
| `GET` | `/items` | Plain proxy |
| `GET` | `/my-items` | `POST /verify`, inject `x-user-id` / `x-user-email`, strip `Authorization` |
| `POST` | `/items/search` | Validate `{category?: string, max_price?: int}` |
| `POST` | `/items/lookup` | Validate `{q}` and rewrite to `{query, limit, source}` |

## Run

```bash
docker compose up --build
```

Local development:

```bash
cd auth-service && go run .
cd data-service && go run .
cd gateway-apigate && cargo run --release
cd gateway-python && ./scripts/run.sh

# Kong/APISIX are Docker-only in this repo:
docker compose up --build gateway-kong
docker compose up --build gateway-apisix
```

## Quick Check

```bash
GW=http://localhost:8080
AUTH=http://localhost:8001

curl -s -X POST "$AUTH/register" \
  -H 'content-type: application/json' \
  -d '{"email":"alice@example.com","password":"hunter22"}'

TOKEN=$(curl -s -X POST "$AUTH/login" \
  -H 'content-type: application/json' \
  -d '{"email":"alice@example.com","password":"hunter22"}' \
  | python3 -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')

curl -s "$GW/items"
curl -s "$GW/my-items" -H "Authorization: Bearer $TOKEN"
curl -s -X POST "$GW/items/search" -H 'content-type: application/json' \
  -d '{"category":"office","max_price":300}'
curl -s -X POST "$GW/items/lookup" -H 'content-type: application/json' \
  -d '{"q":"pen"}'
```

## Load Test

Latest run: 4 vCPU / 10 GiB Linux, one gateway at a time.
Full numbers and apigate percentage advantage per scenario:
[load-tests/RESULTS.md](load-tests/RESULTS.md).

Latest headline:

| Profile | Main result |
|---|---|
| steady, 2500 RPS | apigate p99 is 33-144% faster than APISIX, 52-391% faster than Kong, 317-3857% faster than Python depending on route |
| ramp, 0 -> 20000 RPS | apigate delivered 6-31% more avg RPS than APISIX, 1-41% more than Kong, 115-184% more than Python |
| stress, 9000 RPS | apigate p99 is 7-70% faster than APISIX, 32-159% faster than Kong, and orders of magnitude faster than Python on saturated routes |
| direct data baseline | `data-service` reaches ~19.4-19.8k peak RPS in ramp with p99 under 56 ms; it is not the primary ramp bottleneck for `items`, `search`, or `lookup` |

Run matrix:

```bash
docker compose up -d auth data gateway-apigate cadvisor
./load-tests/run.sh apigate http://localhost:8080

docker compose stop gateway-apigate
docker compose up -d gateway-kong
./load-tests/run.sh kong http://localhost:8090

docker compose stop gateway-kong
docker compose up -d gateway-apisix
./load-tests/run.sh apisix http://localhost:8093

docker compose stop gateway-apisix
docker compose up -d gateway-python
./load-tests/run.sh python http://localhost:8092
```

Direct data-service baseline:

```bash
docker compose up -d data cadvisor
./load-tests/run.sh data
```

Use it to separate a `data-service` throughput ceiling from a gateway ceiling.
In direct mode, `/my-items` sends internal identity headers and `/lookup` sends
the already-rewritten internal body.

## Fairness Knobs

Assumed host: 4 vCPU Linux.

| Setting | apigate | Kong | APISIX | Python |
|---|---:|---:|---:|---:|
| workers | 4 tokio threads | 4 nginx workers | 4 nginx workers | 4 granian workers |
| listen capacity | 4096 | 1024 x 4 | 1024 x 4 | practical cap 4096 |
| upstream pool per upstream | 2048 | 512 x 4 | 512 x 4 | 512 x 4 |
| connect timeout | 3s | 3s | 3s | 3s |
| data total timeout | 10s | 10s | 10s | 10s |
| auth total timeout | 3s | 3s | 3s | 3s |
| pool idle | 120s | 120s | 120s | 120s |
| TCP keepalive | 30s | 30s via container sysctl | 30s via container sysctl | 30s |
| allocator | mimalloc | jemalloc | jemalloc | jemalloc |

Host requirements:

```bash
ulimit -n          # >= 65536
sysctl net.core.somaxconn  # >= 8192
```

Recommended sysctl baseline:

```conf
net.core.somaxconn = 8192
net.ipv4.tcp_max_syn_backlog = 8192
net.core.netdev_max_backlog = 5000
net.ipv4.ip_local_port_range = 10000 65535
net.ipv4.tcp_tw_reuse = 1
```

## Notes

- `/my-items` stress is partly system-bound because `auth-service`, `data-service`, and the gateway share the same 4 vCPUs.
- Direct `data-service` baseline excludes `auth-service`; use it only to separate data backend capacity from gateway overhead.
- Kong/APISIX keepalive request caps are set to `1000000`; apigate/Python do not expose an equivalent per-connection request cap.
- Result files currently live under `load-tests/results/results/`.
