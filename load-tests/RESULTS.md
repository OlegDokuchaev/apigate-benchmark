# Benchmark results

Matrix run on **4 vCPU / 10 GiB Linux**, host tuned per `README.md` §Host requirements 
(`ulimit -n=65536`, `net.core.somaxconn=8192`, `tcp_tw_reuse=1`). cAdvisor sampled at 1 Hz, 
3 s warmup dropped from each resource window.

Profiles (see `load-tests/k6/lib/profiles.js`):

| Profile | Shape                                | Threshold (abort)                          |
|---------|--------------------------------------|--------------------------------------------|
| steady  | 2 500 RPS × 2 min                    | failed < 1 % (no abort)                    |
| ramp    | 0 → 20 000 RPS over 5 min            | p99 < 1 s **and** failed < 5 % (abort, 15 s grace) |
| stress  | 10 000 RPS × 1 min                   | none — observe degradation, don't assert   |

All three gateways receive identical inbound load from k6 (open-model) against the same 
upstreams (`auth:8001` Go fasthttp, `data:8002` Go fasthttp). One gateway up at a time, 
30 s cooldown between runs.

**apigate is the reference** — every kong / python row carries an `(N× slower / faster)` 
delta vs apigate on the same metric. Latency / CPU / memory: lower is better. RPS: higher 
is better.

Source data: `load-tests/results/results/*.json`.

---

## Headlines

### Steady (2 500 RPS × 2 min) — apigate dominates

| Route    | apigate p99 | kong p99                | python p99               |
|----------|-------------|-------------------------|--------------------------|
| items    |     1.82 ms | 3.23 ms (1.78× slower) | 8.06 ms (4.44× slower) |
| my-items |     3.60 ms | 9.12 ms (2.54× slower) | 80.4 ms (22.35× slower) |
| search   |     1.72 ms | 2.82 ms (1.63× slower) | 21.5 ms (12.50× slower) |
| lookup   |     1.65 ms | 2.87 ms (1.74× slower) | 20.5 ms (12.42× slower) |

All three sustain 2 500 RPS at 0 % errors. apigate p99 stays **sub-4 ms** on every route. 
Kong is 1.6–2.5× slower at p99; python is 4.4–22× slower at p99 (`/my-items` is the worst 
case for python).

### Ramp (0 → 20 000 RPS over 5 min) — saturation points

With the `p99 < 1000 ms` abort threshold, each cell terminates exactly when its gateway 
crosses the latency ceiling. The duration column reads as a saturation thermometer: 
longer = the gateway pushed further into the ramp before saturating. Approximate peak 
achievable RPS ≈ 2 × avg RPS (linear-ramp integral).

| Route    | Gateway | Duration            | avg RPS | est. peak | p99 at abort | err |
|----------|---------|---------------------|---------|-----------|--------------|-----|
| items    | apigate |   278 s (92.6 %)    |   7,431 | ~14,862    |      1.21 s  |      0 |
| items    | kong    |   239 s (79.8 %)    |   6,590 | ~13,179    |      1.06 s  |      0 |
| items    | python  |   102 s (34.1 %)    |   3,236 | ~6,473    |      1.18 s  |      0 |
| my-items | apigate |    86 s (28.6 %)    |   2,718 | ~5,435    |      1.09 s  |      0 |
| my-items | kong    |   104 s (34.7 %)    |   3,178 | ~6,355    |      1.10 s  |      0 |
| my-items | python  |    54 s (17.8 %)    |   1,707 | ~3,413    |      1.11 s  |      0 |
| search   | apigate |   233 s (77.7 %)    |   6,620 | ~13,241    |      1.01 s  |      0 |
| search   | kong    |   199 s (66.3 %)    |   5,579 | ~11,157    |      1.06 s  |      0 |
| search   | python  |    94 s (31.3 %)    |   2,963 | ~5,927    |      1.05 s  |      0 |
| lookup   | apigate |   256 s (85.3 %)    |   6,644 | ~13,288    |      1.49 s  |  1.03% |
| lookup   | kong    |   191 s (63.6 %)    |   5,465 | ~10,931    |      1.06 s  |      0 |
| lookup   | python  |    96 s (31.9 %)    |   2,951 | ~5,901    |      1.08 s  |      0 |

Reading off the non-auth routes (`items` / `search` / `lookup`):

- **apigate** saturates around **13 000–15 000 RPS** on a 4-vCPU host (avg 6 620–7 431, 
  ≈ ½ × peak). The 0 → 10 000 ramp profile from earlier benchmark generations never 
  reached this point — apigate had ≥ 50 % CPU headroom there.
- **kong** saturates around **11 000–13 000 RPS** (avg 5 465–6 590). ~15 % below apigate.
- **python (granian + aiohttp)** saturates around **3 000–3 500 achievable RPS** 
  (avg 2 951–3 236). Aborts within the first third of the ramp on every route.

`/my-items` ceiling for all three is governed by **auth-service saturation on the shared 
4-vCPU host**, not by the gateway code — see system-bound caveat in §Caveats.

### Stress (10 000 RPS × 1 min) — degradation vs comfort

| Route    | apigate p99 / err  | kong p99 / err              | python p99 / err          |
|----------|--------------------|-----------------------------|---------------------------|
| items    |       264.2 ms / 0 | 338.5 ms / 0                | 60.00 s / 1.87%           |
| my-items |    7.13 s / 77.29% | 20.69 s / 26.73%            | 60.00 s / 2.93%           |
| search   |       272.3 ms / 0 | 659.0 ms / 0                | 60.00 s / 2.14%           |
| lookup   |       360.6 ms / 0 | 627.5 ms / 0                | 60.00 s / 2.15%           |

- **apigate** sustains 10 000 RPS on `items`/`search`/`lookup` with **0 % errors and p99 
  264–361 ms, CPU 65–70 % avg** — still has headroom; this is below saturation.
- **kong** holds 0 % errors but p99 climbs to 339–659 ms with **CPU 98–116 % avg** — 
  squarely at its single-host ceiling.
- **python** can only sustain ~3 200–3 600 RPS at this target — p99 hits the 60 s client-side 
  timeout and 1.9–2.1 % of requests fail outright.
- `/my-items` saturates auth differently in each gateway: **apigate** surfaces it as 
  77 % errors / p99 7 s (pass-through honesty); **kong** queues internally → 27 % errors / 
  p99 21 s; **python** drops most via granian backpressure → only 3 % surfaced errors but 
  p99 60 s on what does flow.

---

## Steady — `constant-arrival-rate` 2 500 RPS × 2 min

### items — `GET /items` (bare proxy, baseline)

| Gateway | RPS | p50 | p95 | p99 | err | CPU avg | Mem peak |
|---|---|---|---|---|---|---|---|
| **apigate** (baseline) | 2,500 | 0.34 ms | 0.69 ms | 1.82 ms | 0 | 35% | 53 MiB |
| kong | 2,500 | 0.39 ms (1.14× slower) | 0.92 ms (1.34× slower) | 3.23 ms (1.78× slower) | 0 | 43% (1.26× more) | 560 MiB (10.54× more) |
| python | 2,500 | 0.83 ms (2.44× slower) | 2.70 ms (3.92× slower) | 8.06 ms (4.44× slower) | 0 | 105% (3.03× more) | 192 MiB (3.61× more) |

### my-items — `GET /my-items` (auth hook calls `POST /verify`)

| Gateway | RPS | p50 | p95 | p99 | err | CPU avg | Mem peak |
|---|---|---|---|---|---|---|---|
| **apigate** (baseline) | 2,496 | 0.50 ms | 1.08 ms | 3.60 ms | 0 | 56% | 69 MiB |
| kong | 2,496 | 0.74 ms (1.48× slower) | 3.22 ms (3.00× slower) | 9.12 ms (2.54× slower) | 0 | 83% (1.48× more) | 561 MiB (8.14× more) |
| python | 2,496 | 4.42 ms (8.84× slower) | 33.2 ms (30.84× slower) | 80.4 ms (22.35× slower) | 0 | 164% (2.93× more) | 196 MiB (2.85× more) |

### search — `POST /items/search` (typed body validation)

| Gateway | RPS | p50 | p95 | p99 | err | CPU avg | Mem peak |
|---|---|---|---|---|---|---|---|
| **apigate** (baseline) | 2,500 | 0.33 ms | 0.70 ms | 1.72 ms | 0 | 38% | 69 MiB |
| kong | 2,500 | 0.43 ms (1.33× slower) | 0.94 ms (1.35× slower) | 2.82 ms (1.63× slower) | 0 | 52% (1.38× more) | 557 MiB (8.13× more) |
| python | 2,500 | 1.71 ms (5.24× slower) | 7.90 ms (11.35× slower) | 21.5 ms (12.50× slower) | 0 | 145% (3.84× more) | 200 MiB (2.92× more) |

### lookup — `POST /items/lookup` (validate + body rewrite)

| Gateway | RPS | p50 | p95 | p99 | err | CPU avg | Mem peak |
|---|---|---|---|---|---|---|---|
| **apigate** (baseline) | 2,500 | 0.33 ms | 0.69 ms | 1.65 ms | 0 | 38% | 69 MiB |
| kong | 2,500 | 0.47 ms (1.43× slower) | 1.04 ms (1.50× slower) | 2.87 ms (1.74× slower) | 0 | 56% (1.48× more) | 549 MiB (7.91× more) |
| python | 2,500 | 1.62 ms (4.91× slower) | 7.30 ms (10.51× slower) | 20.5 ms (12.42× slower) | 0 | 145% (3.85× more) | 198 MiB (2.85× more) |


## Ramp — `ramping-arrival-rate` 0 → 20 000 RPS over 5 min (abort on p99 > 1 s)

### items — `GET /items` (bare proxy, baseline)

| Gateway | RPS | p50 | p95 | p99 | err | CPU avg | Mem peak |
|---|---|---|---|---|---|---|---|
| **apigate** (baseline) | 7,431 | 12.8 ms | 284.6 ms | 1.21 s | 0 | 64% | 654 MiB |
| kong | 6,590 (-11.3%) | 35.0 ms (2.73× slower) | 467.1 ms (1.64× slower) | 1.06 s (1.15× faster) | 0 | 83% (1.29× more) | 693 MiB (1.06×) |
| python | 3,236 (-56.4%) | 12.5 ms (0.97×) | 542.6 ms (1.91× slower) | 1.18 s (0.97×) | 0 | 116% (1.80× more) | 308 MiB (2.12× less) |

_dropped iterations:_ apigate 425,037 · kong 295,258 · python 14,123.
_run reached:_ apigate 278s (93%) · kong 239s (80%) · python 102s (34%).

### my-items — `GET /my-items` (auth hook calls `POST /verify`)

| Gateway | RPS | p50 | p95 | p99 | err | CPU avg | Mem peak |
|---|---|---|---|---|---|---|---|
| **apigate** (baseline) | 2,718 | 0.60 ms | 195.8 ms | 1.09 s | 0 | 54% | 555 MiB |
| kong | 3,178 (+16.9%) | 18.9 ms (31.77× slower) | 640.1 ms (3.27× slower) | 1.10 s (1.01×) | 0 | 97% (1.80× more) | 670 MiB (1.21× more) |
| python | 1,707 (-37.2%) | 3.83 ms (6.43× slower) | 607.5 ms (3.10× slower) | 1.11 s (1.02×) | 0 | 108% (2.00× more) | 305 MiB (1.82× less) |

_dropped iterations:_ apigate 6,923 · kong 21,022 · python 830.
_run reached:_ apigate 86s (29%) · kong 104s (35%) · python 54s (18%).

### search — `POST /items/search` (typed body validation)

| Gateway | RPS | p50 | p95 | p99 | err | CPU avg | Mem peak |
|---|---|---|---|---|---|---|---|
| **apigate** (baseline) | 6,620 | 5.46 ms | 334.1 ms | 1.01 s | 0 | 60% | 648 MiB |
| kong | 5,579 (-15.7%) | 18.6 ms (3.40× slower) | 636.0 ms (1.90× slower) | 1.06 s (1.05×) | 0 | 87% (1.45× more) | 692 MiB (1.07×) |
| python | 2,963 (-55.2%) | 20.1 ms (3.68× slower) | 656.7 ms (1.97× slower) | 1.05 s (1.04×) | 0 | 132% (2.21× more) | 317 MiB (2.04× less) |

_dropped iterations:_ apigate 217,959 · kong 182,719 · python 9,488.
_run reached:_ apigate 233s (78%) · kong 199s (66%) · python 94s (31%).

### lookup — `POST /items/lookup` (validate + body rewrite)

| Gateway | RPS | p50 | p95 | p99 | err | CPU avg | Mem peak |
|---|---|---|---|---|---|---|---|
| **apigate** (baseline) | 6,644 | 16.5 ms | 336.2 ms | 1.49 s | 1.03% | 68% | 716 MiB |
| kong | 5,465 (-17.7%) | 57.3 ms (3.46× slower) | 635.6 ms (1.89× slower) | 1.06 s (1.41× faster) | 0 | 89% (1.31× more) | 683 MiB (0.95×) |
| python | 2,951 (-55.6%) | 19.0 ms (1.15× slower) | 762.4 ms (2.27× slower) | 1.08 s (1.37× faster) | 0 | 137% (2.02× more) | 331 MiB (2.16× less) |

_dropped iterations:_ apigate 412,062 · kong 140,932 · python 16,758.
_run reached:_ apigate 256s (85%) · kong 191s (64%) · python 96s (32%).


## Stress — `constant-arrival-rate` 10 000 RPS × 1 min

### items — `GET /items` (bare proxy, baseline)

| Gateway | RPS | p50 | p95 | p99 | err | CPU avg | Mem peak |
|---|---|---|---|---|---|---|---|
| **apigate** (baseline) | 9,715 | 1.14 ms | 136.5 ms | 264.2 ms | 0 | 65% | 161 MiB |
| kong | 9,246 (-4.8%) | 27.3 ms (23.99× slower) | 218.4 ms (1.60× slower) | 338.5 ms (1.28× slower) | 0 | 98% (1.51× more) | 638 MiB (3.95× more) |
| python | 3,553 (-63.4%) | 564.1 ms (496.53× slower) | 1.67 s (12.22× slower) | 60.00 s (227.12× slower) | 1.87% | 119% (1.84× more) | 373 MiB (2.31× more) |

_dropped iterations:_ apigate 17,068 · kong 43,164 · python 283,572.

### my-items — `GET /my-items` (auth hook calls `POST /verify`)

| Gateway | RPS | p50 | p95 | p99 | err | CPU avg | Mem peak |
|---|---|---|---|---|---|---|---|
| **apigate** (baseline) | 2,617 | 3.23 s | 6.26 s | 7.13 s | 77.29% | 208% | 784 MiB |
| kong | 1,695 (-35.2%) | 1.42 s (2.27× faster) | 16.19 s (2.59× slower) | 20.69 s (2.90× slower) | 26.73% | 265% (1.27× more) | 798 MiB (1.02×) |
| python | 2,601 | 1.18 s (2.74× faster) | 1.86 s (3.37× faster) | 60.00 s (8.42× slower) | 2.93% | 166% (1.25× less) | 393 MiB (2.00× less) |

_dropped iterations:_ apigate 434,980 · kong 474,931 · python 398,223.

### search — `POST /items/search` (typed body validation)

| Gateway | RPS | p50 | p95 | p99 | err | CPU avg | Mem peak |
|---|---|---|---|---|---|---|---|
| **apigate** (baseline) | 9,384 | 5.60 ms | 159.5 ms | 272.3 ms | 0 | 70% | 555 MiB |
| kong | 8,512 (-9.3%) | 180.8 ms (32.27× slower) | 502.0 ms (3.15× slower) | 659.0 ms (2.42× slower) | 0 | 111% (1.58× more) | 699 MiB (1.26× more) |
| python | 3,261 (-65.3%) | 808.6 ms (144.31× slower) | 1.47 s (9.23× slower) | 60.00 s (220.35× slower) | 2.14% | 136% (1.94× more) | 388 MiB (1.43× less) |

_dropped iterations:_ apigate 36,851 · kong 88,466 · python 324,226.

### lookup — `POST /items/lookup` (validate + body rewrite)

| Gateway | RPS | p50 | p95 | p99 | err | CPU avg | Mem peak |
|---|---|---|---|---|---|---|---|
| **apigate** (baseline) | 9,284 | 3.77 ms | 210.5 ms | 360.6 ms | 0 | 69% | 517 MiB |
| kong | 8,607 (-7.3%) | 153.4 ms (40.69× slower) | 415.1 ms (1.97× slower) | 627.5 ms (1.74× slower) | 0 | 116% (1.69× more) | 695 MiB (1.35× more) |
| python | 3,169 (-65.9%) | 800.3 ms (212.28× slower) | 1.46 s (6.92× slower) | 60.00 s (166.39× slower) | 2.15% | 127% (1.86× more) | 381 MiB (1.36× less) |

_dropped iterations:_ apigate 41,596 · kong 83,396 · python 325,345.


---

## Reading the deltas

- **`(N× slower)` / `(N× faster)`** on latency cells means kong/python p99 (or p50/p95) 
  is N times the apigate value. `(1.78× slower)` = 78 % more wall-time at that percentile.
- **`(±N %)`** on RPS cells is the relative throughput delta vs apigate. Negative = the cell 
  achieved fewer requests (ramp aborted earlier; or stress gateway couldn't absorb target rate).
- **`(N× more)` / `(N× less)`** on CPU and memory means N times the resource consumption. 
  CPU is per-core %: `100 % = one full vCPU`. Memory is cAdvisor working_set peak.
- **err %** is `http_req_failed.rate` from k6 — non-2xx + transport failures (timeouts, 
  connection resets). 0 means a clean run.
- **ramp `run reached: <s> (<%>)`** is the fraction of the planned 5 min the cell ran before 
  the abort threshold tripped. 100 % = no abort. Lower = saturated earlier.

## Caveats

- One run per cell, not averaged across replicates. Run-to-run variance on a 4 vCPU host 
  is ~5–10 % for steady p99, more under stress.
- **Stress 1 min is short.** First ~30 s is warm-up (TCP pool fill, msr connection setup), 
  leaving ~30 s of stationary stress data. p99 noise scales accordingly. To find apigate's 
  own stress ceiling specifically, override per gateway: `STRESS_RPS=15000 ./run.sh apigate ...`.
- **`/my-items` is system-bound, not gateway-bound.** `auth-service`, `data-service` and 
  the gateway all share the same 4 vCPUs. Under stress, auth saturates at ~3–4k achievable 
  /verify per second regardless of gateway. The three error/latency profiles on `/my-items` 
  reflect *how each gateway exposes auth saturation*, not how each gateway compares on 
  auth-pipeline overhead. For a clean gateway-side test, run `auth-service` on a separate host.
- **Stress at 10 000 RPS leaves apigate well below saturation** — its p99 264–361 ms and 65 % 
  CPU are not its breaking point. The ramp profile (which goes to 20 000) is what locates 
  apigate's actual ceiling.
- `cAdvisor` itself uses ~0.5–1 % CPU; included in the report so the measurer's footprint is 
  visible. Cap: `cpus: '0.5'`, `memory: 256M`.
