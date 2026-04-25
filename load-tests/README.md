# load-tests

[k6](https://k6.io/) matrix for comparing the three gateway implementations
(`gateway-apigate`, `gateway-kong`, `gateway-python`) under identical load.
Each run executes one profile × one route × one gateway and writes a
per-run JSON summary. When [cAdvisor](https://github.com/google/cadvisor) is
running alongside (included in the compose stack), per-container CPU /
memory / network stats are pulled for every iteration.

## Layout

```
load-tests/
├── run.sh                      # driver: loops profile × route for one gateway
├── k6/
│   ├── scenario.js             # entry point; reads ROUTE / PROFILE / GATEWAY_* env
│   └── lib/
│       ├── profiles.js         # steady / ramp / stress (all open-model)
│       ├── routes.js           # one function per public route
│       └── summary.js          # textSummary → stdout, metrics → results/*.json
├── scripts/
│   └── collect_resources.py    # pulls cAdvisor stats after each k6 run → JSON aggregate
└── results/                    # per-run artifacts, created on first run
```

## Matrix

Three profiles × four routes = **12 runs per gateway**. `run.sh` iterates
the full matrix in this order: `steady → ramp → stress`, and within each
profile `items → my-items → search → lookup`.

| Profile | Executor                 | Default shape                |
|---------|--------------------------|------------------------------|
| steady  | `constant-arrival-rate`  | 2500 RPS × 2 min             |
| ramp    | `ramping-arrival-rate`   | 0 → 10000 RPS over 5 min     |
| stress  | `constant-arrival-rate`  | 12000 RPS × 1 min            |

| Route     | Method / Path         | Exercises                                          |
|-----------|-----------------------|----------------------------------------------------|
| items     | `GET /items`          | Bare proxy (baseline).                             |
| my-items  | `GET /my-items`       | Auth hook: gateway calls `POST /verify` per request. |
| search    | `POST /items/search`  | Typed body validation.                             |
| lookup    | `POST /items/lookup`  | Typed validation + body rewrite (`{q}` → internal shape). |

All profiles are open-model: RPS is pinned, latency reflects the gateway's
state rather than VU-pool saturation. Thresholds vary per profile:

- `steady` asserts `http_req_failed < 1 %` — the gateway should be fine here.
- `ramp` aborts the cell on either signal: `p99 > 1 s` (quality past usable)
  **or** `http_req_failed > 5 %` (gateway dropping connections / timing out).
  Failure rate is the faster signal because k6 evaluates `p99` globally over
  the whole run — a flood of timeouts late in the ramp gets averaged out by
  the fast samples from the early phase. The first 15 s are excluded so
  connection-setup spikes don't trip either threshold prematurely.
- `stress` has no thresholds: we want to observe degradation, not assert it.

## Running

Bring up **one** gateway at a time — leave the others stopped so they
don't share CPU. Include `cadvisor` if you want resource metrics:

```bash
docker compose up -d auth data gateway-apigate cadvisor
./load-tests/run.sh apigate http://localhost:8080

docker compose stop gateway-apigate
docker compose up -d gateway-kong
./load-tests/run.sh kong http://localhost:8090

docker compose stop gateway-kong
docker compose up -d gateway-python
./load-tests/run.sh python http://localhost:8092
```

Each invocation writes, for `<key> = <gateway>_<route>_<profile>`:

| File                     | Producer               | Contents                                                                       |
|--------------------------|------------------------|--------------------------------------------------------------------------------|
| `<key>.json`             | k6 `handleSummary`     | Meta block + full k6 metrics object.                                           |
| `<key>_resources.json`   | `collect_resources.py` | Per-container min/avg/p50/p95/p99/max for CPU%, memory + network/throttle deltas. |

The `_resources.json` file is written only when cAdvisor is reachable —
see [Resource collection](#resource-collection) below.

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
| `SAMPLE_RESOURCES` | `1`                            | Set to `0` to skip cAdvisor collection.                       |
| `CADVISOR_URL`     | `http://localhost:8099`        | Where `collect_resources.py` looks for cAdvisor.              |
| `WARMUP`           | `3`                            | Seconds dropped from the start of each resource sample series. |

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

## Resource collection

cAdvisor runs as a sidecar in `docker-compose.yml`. It samples every
running container once per second and buffers the last 10 minutes of
stats in memory. `run.sh` records a `[start_ts, end_ts]` window around
each k6 iteration, and afterwards `scripts/collect_resources.py` makes
one HTTP request per container to `GET /api/v2.0/stats/<id>?type=docker`,
slices the buffer to the window, and writes the aggregated JSON.

- **Post-hoc, not live.** Nothing runs during the k6 iteration — cAdvisor
  buffers passively, we pull it all in one shot when the run finishes.
  There's no background process to orphan if `run.sh` is interrupted.
- **Measurer footprint is visible.** `cadvisor` is included in the sample
  set, so its CPU/memory cost shows up in the same report as the gateway
  it's measuring. Typical footprint on a benchmark host: ~0.5 % CPU,
  ~15 MiB RSS — capped at `cpus: '0.5'` / `memory: 256M` in compose.
- **Sample rate: 1 Hz.** Configured via `--housekeeping_interval=1s`; override
  in `docker-compose.yml` if you need finer or coarser resolution. 1 Hz
  gives ~120 / ~300 / ~60 samples for steady / ramp / stress.
- **CPU% is per-core.** Computed as `delta(cpu.usage.total_ns) /
  delta(wall_time_ns) * 100`. Follows Docker's convention: `100 %` is one
  full core, `400 %` is four cores saturated.
- **Memory is `working_set`.** cgroup `usage - inactive_file` — the
  "operator-visible RSS" that `kubectl top` / `docker stats` show. Includes
  active page cache; strict RSS / cache breakdowns are pulled from cAdvisor
  too but only the working-set aggregate ends up in the report.
- **Container discovery.** `run.sh` resolves each compose service via its
  `com.docker.compose.service` label, then passes container names to
  `collect_resources.py`. The collector looks up the container ID through
  `docker inspect` — cAdvisor keys stats by ID.
- **Warmup.** The default 3 s warmup drops the very first samples (k6's
  `register` / `login` bcrypt spike on auth for `my-items` plus TCP-pool
  warm-up in all three gateways).

Skip collection with `SAMPLE_RESOURCES=0 ./run.sh ...`, e.g. when running a
gateway locally outside Docker (`cargo run` / `python -m granian`). The
collector is auto-disabled if cAdvisor's `/healthz` endpoint is unreachable
at `CADVISOR_URL`, or if `docker` / `python3` aren't on `PATH`.

Compact stderr line after each run, for quick eyeballing:

```
[resources] window=60.0s samples=232 warmup=3.0s
[resources] gateway-apigate-1    cpu avg= 142.1% p95= 183.4% max= 201.2%  mem peak=  17.8 MiB  throttled=   0.0ms
[resources] auth-1               cpu avg=  24.3% p95=  31.8% max=  34.9%  mem peak=  12.4 MiB  throttled=   0.0ms
[resources] data-1               cpu avg=  38.5% p95=  47.2% max=  49.7%  mem peak=   8.1 MiB  throttled=   0.0ms
[resources] cadvisor             cpu avg=   0.5% p95=   0.7% max=   0.9%  mem peak=  14.8 MiB  throttled=   0.0ms
```

`throttled` is CFS throttled time over the window; non-zero means the
container was pinned against its `--cpus` limit. A healthy benchmark run
shows 0 ms throttling for the gateway (no CPU cap on it, only on cAdvisor).

### A note on Docker Desktop macOS

cAdvisor works on Docker Desktop but needs an explicit `/var/run/docker.sock`
bind (included in this repo's compose). For public benchmark numbers prefer
a Linux host — the VM layer adds noise.

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
- **Thresholds.** Per-profile, listed in [Matrix](#matrix) above; defined
  in `k6/lib/profiles.js` alongside the profile registry.
- **30 s cooldown between runs.** Lets upstream TCP connections drain
  (TIME_WAIT ≈ 60 s on Linux, 30 s is a compromise between isolation and
  total matrix wall-clock time). Override with `COOLDOWN=60`.
- **cAdvisor is capped and counted.** It runs as a normal compose service
  (it has to, to see cgroup counters) but is limited to `cpus: '0.5'` /
  `memory: 256M`, and its own footprint is sampled into the same report.
  A gateway showing "3 cores used" next to a cAdvisor showing "0.4 % used"
  tells you the measurer isn't distorting the picture.
