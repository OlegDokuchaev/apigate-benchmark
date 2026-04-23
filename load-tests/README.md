# load-tests

[k6](https://k6.io/) matrix for comparing the three gateway implementations
(`gateway-apigate`, `gateway-kong`, `gateway-python`) under identical load.
Each run executes one profile × one route × one gateway and writes a
per-run JSON summary.

## Layout

```
load-tests/
├── run.sh                 # driver: loops profile × route for one gateway
├── k6/
│   ├── scenario.js        # entry point; reads ROUTE / PROFILE / GATEWAY_* env
│   └── lib/
│       ├── profiles.js    # steady / ramp / stress (all open-model)
│       ├── routes.js      # one function per public route
│       └── summary.js     # textSummary → stdout, metrics → results/*.json
└── results/               # per-run summaries, created on first run
```

## Matrix

Three profiles × four routes = **12 runs per gateway**. `run.sh` iterates
the full matrix in this order: `steady → ramp → stress`, and within each
profile `items → my-items → search → lookup`.

| Profile | Executor                 | Default shape                |
|---------|--------------------------|------------------------------|
| steady  | `constant-arrival-rate`  | 500 RPS × 2 min              |
| ramp    | `ramping-arrival-rate`   | 0 → 2000 RPS over 5 min      |
| stress  | `constant-arrival-rate`  | 2500 RPS × 1 min             |

| Route     | Method / Path         | Exercises                                          |
|-----------|-----------------------|----------------------------------------------------|
| items     | `GET /items`          | Bare proxy (baseline).                             |
| my-items  | `GET /my-items`       | Auth hook: gateway calls `POST /verify` per request. |
| search    | `POST /items/search`  | Typed body validation.                             |
| lookup    | `POST /items/lookup`  | Typed validation + body rewrite (`{q}` → internal shape). |

All profiles are open-model: RPS is pinned, latency reflects the gateway's
state rather than VU-pool saturation. Thresholds (`http_req_failed < 1 %`)
apply only to `steady`; `ramp` / `stress` deliberately push past the green
zone, so a pass/fail threshold there would just add noise.

## Running

Bring up **one** gateway at a time — leave the others stopped so they
don't share CPU:

```bash
docker compose up -d auth data gateway-apigate
./load-tests/run.sh apigate http://localhost:8080

docker compose stop gateway-apigate
docker compose up -d gateway-kong
./load-tests/run.sh kong http://localhost:8090

docker compose stop gateway-kong
docker compose up -d gateway-python
./load-tests/run.sh python http://localhost:8092
```

Each invocation writes `results/<gateway>_<route>_<profile>.json` with
the meta block (gateway / route / profile) and the full k6 metrics object.

## Overrides

Per-profile RPS and duration overrides are plain env vars:

```bash
STEADY_RPS=800 STEADY_DURATION=5m STRESS_RPS=4000 \
  ./run.sh apigate http://localhost:8080
```

Full knob list (see `k6/lib/profiles.js`):

| Profile | Vars                                                                   |
|---------|------------------------------------------------------------------------|
| steady  | `STEADY_RPS`, `STEADY_DURATION`, `STEADY_VUS`, `STEADY_MAX_VUS`        |
| ramp    | `RAMP_START`, `RAMP_END`, `RAMP_DURATION`, `RAMP_VUS`, `RAMP_MAX_VUS`  |
| stress  | `STRESS_RPS`, `STRESS_DURATION`, `STRESS_VUS`, `STRESS_MAX_VUS`        |

Driver-level overrides for `run.sh`:

| Var                | Default                        | Purpose                                   |
|--------------------|--------------------------------|-------------------------------------------|
| `AUTH_URL`         | `http://localhost:8001`        | Where the setup phase obtains a JWT.      |
| `ROUTES_OVERRIDE`  | `items my-items search lookup` | Subset / reorder of routes.               |
| `PROFILES_OVERRIDE`| `steady ramp stress`           | Subset / reorder of profiles.             |
| `COOLDOWN`         | `30`                           | Seconds to pause between runs (TIME_WAIT drain after stress). |

Run a single cell of the matrix directly with k6 if you don't need the
matrix:

```bash
k6 run \
  -e GATEWAY_NAME=apigate \
  -e GATEWAY_URL=http://localhost:8080 \
  -e ROUTE=my-items \
  -e PROFILE=steady \
  k6/scenario.js
```

## Metrics tagging

Each run attaches three global tags — `gateway`, `profile`, `route` — to
every metric sample. When merging results across runs you can slice by
any combination without parsing filenames.

## Design notes

- **Open-model profiles.** `constant-arrival-rate` / `ramping-arrival-rate`
  let k6 allocate VUs as needed to sustain the target RPS. `preAllocatedVUs`
  is the starting pool; `maxVUs` caps how far k6 can scale it. If you see
  k6 warnings about dropped iterations, bump `*_MAX_VUS`.
- **Setup only runs when needed.** `my-items` is the only route that needs
  a JWT, so `setup()` short-circuits for the other three — registration +
  login happen at most once per run.
- **Bodies pre-serialised.** `searchBody` / `lookupBody` are stringified
  once at module load, not per iteration.
- **Response bodies discarded.** `discardResponseBodies: true` keeps k6
  from allocating response buffers we don't need — the benchmark cares
  about status code and latency, not payload contents.
- **Thresholds only in `steady`.** `ramp` / `stress` intentionally hit the
  failure regime; an assert-style `http_req_failed < 1 %` would turn those
  into red runs for reasons the benchmark is meant to measure.
- **30 s cooldown between runs.** Lets upstream TCP connections drain
  (TIME_WAIT ≈ 60 s on Linux, 30 s is a compromise between isolation and
  total matrix wall-clock time). Override with `COOLDOWN=60`.
