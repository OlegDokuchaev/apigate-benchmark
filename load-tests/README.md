# load-tests

k6 matrix runner for the four gateways. Resource metrics come from cAdvisor.

## Matrix

| Profile | Shape | Threshold |
|---|---|---|
| `steady` | 2500 RPS x 2 min | fail if scenario error rate >= 1% |
| `ramp` | 0 -> 20000 RPS over 5 min | abort after 15s if p99 >= 1s or errors >= 5% |
| `stress` | 9000 RPS x 1 min | no threshold |

| Route | Path | Work |
|---|---|---|
| `items` | `GET /items` | plain proxy |
| `my-items` | `GET /my-items` | auth hook + proxy |
| `search` | `POST /items/search` | body validation |
| `lookup` | `POST /items/lookup` | validation + body rewrite |

Gateway matrix: `4 gateways x 4 routes x 3 profiles = 48 runs`.
Direct data baseline: `1 target x 4 routes x 3 profiles = 12 runs`.

## Latest Results

See [RESULTS.md](RESULTS.md).

Apigate advantage from the latest 4-vCPU Linux run:

| Profile | Metric | vs APISIX | vs Kong | vs Python |
|---|---|---:|---:|---:|
| steady | p99 latency speedup | 33-144% | 52-391% | 317-3857% |
| ramp | achieved RPS advantage | 6-31% | 1-41% | 115-184% |
| stress | p99 latency speedup | 7-70% | 32-159% | 669-28376% |

`/my-items` is partly system-bound because auth/data/gateway share the same 4 vCPU host.
Direct `data-service` reaches ~19.4-19.8k peak RPS in ramp with p99 under 56 ms, so `data-service` is not the primary ramp bottleneck for `items`, `search`, or `lookup`.

## Run Gateways

Bring up one gateway at a time:

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

## Run Data Baseline

Use this to check whether the stress ceiling comes from `data-service` rather
than from a gateway:

```bash
docker compose up -d data cadvisor
./load-tests/run.sh data
```

`data` defaults to `http://localhost:8002` and uses the direct internal service
contract:

| Route | Direct behavior |
|---|---|
| `items` | same `GET /items` |
| `my-items` | sends `x-user-id` / `x-user-email`; no auth-service call |
| `search` | same `POST /items/search` body |
| `lookup` | sends `{query, limit, source}` instead of public `{q}` |

If direct `data` saturates near the same RPS as a gateway, the bottleneck is
probably service-side. If direct `data` is much higher, the gateway path is the
limiting layer for that route. For `/my-items`, this baseline intentionally
excludes auth-service; test auth separately if needed.

Each run writes:

| File | Contents |
|---|---|
| `results/<target>_<route>_<profile>.json` | k6 metrics |
| `results/<target>_<route>_<profile>_resources.json` | cAdvisor CPU/memory/network |

Imported latest-result files currently live under `load-tests/results/results/`.

## Overrides

```bash
ROUTES_OVERRIDE="items search" PROFILES_OVERRIDE="steady" \
  ./load-tests/run.sh apigate http://localhost:8080
```

| Env | Default |
|---|---:|
| `AUTH_URL` | `http://localhost:8001` |
| `ROUTES_OVERRIDE` | `items my-items search lookup` |
| `PROFILES_OVERRIDE` | `steady ramp stress` |
| `COOLDOWN` | `30` |
| `SAMPLE_RESOURCES` | `1` |
| `CADVISOR_URL` | `http://localhost:8099` |
| `WARMUP` | `3` |
| `STEADY_RPS` | `2500` |
| `RAMP_END` | `20000` |
| `STRESS_RPS` | `9000` |

Useful per-gateway stress probes:

| Gateway | Suggested `STRESS_RPS` |
|---|---:|
| apigate | `15000` |
| Kong | `12000` |
| APISIX | `12000` |
| Python | `5000` |

## Notes

- Metrics in `RESULTS.md` use scenario-scoped k6 metrics, so setup `/register` or `/login` does not pollute `my-items`.
- CPU is per-core percent: `100%` means one full vCPU.
- Memory is cAdvisor working set.
- cAdvisor is sampled and reported too; it is capped in compose.
