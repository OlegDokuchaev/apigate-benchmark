# Benchmark Results

Run: **4 vCPU / 10 GiB Linux**, one gateway at a time, host tuned per root README.

Source: `load-tests/results/results/*.json`.
Matrix complete: `4 gateways x 4 routes x 3 profiles = 48` gateway summaries plus 48 resource summaries.
Direct `data-service` baseline complete: `1 target x 4 routes x 3 profiles = 12` summaries plus 12 resource summaries.

Metrics:

- `steady`: compare p99 latency. Lower is faster.
- `ramp`: compare achieved avg RPS. Gateway cells abort near p99=1s; direct data did not hit this threshold.
- `stress`: compare p99 latency and achieved RPS at the common 9000 RPS target.
- Error rates are scenario-scoped (`http_req_failed{scenario:...}`), so setup requests do not pollute `my-items`.

## Direct Data Baseline

Direct `data` uses the internal service contract. `my-items` sends identity headers directly and does not call `auth-service`; `lookup` sends the already-rewritten `{query, limit, source}` body.

### Data summary

| Profile | Route | RPS | p99 | err | dropped | data CPU avg | Mem peak |
|---|---|---:|---:|---:|---:|---:|---:|
| steady | items | 2500 | 2.02 ms | 0 | 0 | 17% | 25 MiB |
| steady | my-items | 2500 | 1.82 ms | 0 | 0 | 16% | 25 MiB |
| steady | search | 2500 | 2.41 ms | 0 | 0 | 20% | 27 MiB |
| steady | lookup | 2500 | 2.06 ms | 0 | 0 | 19% | 28 MiB |
| ramp | items | 9888 avg / ~19776 peak | 49.98 ms | 0 | 7927 | 43% | 79 MiB |
| ramp | my-items | 9828 avg / ~19657 peak | 40.94 ms | 0 | 1197 | 40% | 77 MiB |
| ramp | search | 9681 avg / ~19361 peak | 53.46 ms | 0 | 10198 | 46% | 84 MiB |
| ramp | lookup | 9725 avg / ~19450 peak | 55.48 ms | 0 | 3092 | 46% | 84 MiB |
| stress | items | 8986 | 174.0 ms | 0 | 752 | 48% | 83 MiB |
| stress | my-items | 8979 | 194.4 ms | 0 | 1013 | 45% | 78 MiB |
| stress | search | 8967 | 200.1 ms | 0 | 1930 | 51% | 86 MiB |
| stress | lookup | 8954 | 201.9 ms | 0 | 2678 | 51% | 85 MiB |

### What it means

| Route | Ramp: data RPS vs apigate | Stress: data p99 vs apigate | Read |
|---|---:|---:|---|
| items | +44% | 17% lower | data is not the ramp bottleneck; 9000 RPS stress is closer to shared host/network limits |
| my-items | +116% | 98% lower | not apples-to-apples: direct data excludes auth-service and gateway auth work |
| search | +53% | 28% lower | data has enough headroom; gateway path is the ramp ceiling |
| lookup | +55% | 23% lower | data has enough headroom; gateway validation/rewrite path is the ramp ceiling |

Direct data did not return errors. Ramp dropped iterations are below 0.4% of attempted work, so they look like generator/host scheduling pressure near 20k RPS rather than data-service failures.

## Apigate Advantage

### Steady: p99 latency speedup

Formula: `(other_p99 / apigate_p99 - 1) * 100`.

| Route | vs APISIX | vs Kong | vs Python |
|---|---:|---:|---:|
| items | 37% | 62% | 317% |
| my-items | 144% | 391% | 3857% |
| search | 33% | 54% | 975% |
| lookup | 48% | 52% | 1086% |

### Ramp: achieved RPS advantage

Formula: `(apigate_RPS / other_RPS - 1) * 100`.

| Route | vs APISIX | vs Kong | vs Python |
|---|---:|---:|---:|
| items | 6% | 1% | 115% |
| my-items | 31% | 41% | 184% |
| search | 11% | 21% | 146% |
| lookup | 22% | 19% | 119% |

### Stress: p99 latency speedup

Formula: `(other_p99 / apigate_p99 - 1) * 100`.

| Route | vs APISIX | vs Kong | vs Python |
|---|---:|---:|---:|
| items | 37% | 63% | 28376% |
| my-items | 7% | 32% | 669% |
| search | 67% | 90% | 21634% |
| lookup | 70% | 159% | 22852% |

### Stress: achieved RPS advantage

Formula: `(apigate_RPS / other_RPS - 1) * 100`.

| Route | vs APISIX | vs Kong | vs Python |
|---|---:|---:|---:|
| items | 2% | 5% | 143% |
| my-items | 22% | 32% | 73% |
| search | 7% | 7% | 168% |
| lookup | 8% | 11% | 157% |

## Raw Summary

### steady - 2500 RPS x 2 min

| Route | Gateway | RPS | p99 | err | CPU avg | Mem peak |
|---|---|---:|---:|---:|---:|---:|
| items | apigate | 2500 | 1.76 ms | 0 | 37% | 42 MiB |
| items | APISIX | 2500 | 2.40 ms | 0 | 45% | 142 MiB |
| items | Kong | 2500 | 2.84 ms | 0 | 43% | 551 MiB |
| items | Python | 2500 | 7.33 ms | 0 | 106% | 180 MiB |
| my-items | apigate | 2496 | 3.34 ms | 0 | 56% | 59 MiB |
| my-items | APISIX | 2496 | 8.15 ms | 0 | 83% | 147 MiB |
| my-items | Kong | 2496 | 16.38 ms | 0 | 88% | 569 MiB |
| my-items | Python | 2496 | 132.1 ms | 0 | 165% | 201 MiB |
| search | apigate | 2500 | 1.91 ms | 0 | 41% | 59 MiB |
| search | APISIX | 2500 | 2.53 ms | 0 | 53% | 149 MiB |
| search | Kong | 2500 | 2.94 ms | 0 | 54% | 572 MiB |
| search | Python | 2500 | 20.52 ms | 0 | 147% | 204 MiB |
| lookup | apigate | 2500 | 1.86 ms | 0 | 39% | 61 MiB |
| lookup | APISIX | 2500 | 2.75 ms | 0 | 55% | 148 MiB |
| lookup | Kong | 2500 | 2.83 ms | 0 | 57% | 559 MiB |
| lookup | Python | 2500 | 22.05 ms | 0 | 148% | 201 MiB |

### ramp - 0 -> 20000 RPS, abort on p99 >= 1s

| Route | Gateway | avg RPS | delivered peak | p99 | err | dropped |
|---|---|---:|---:|---:|---:|---:|
| items | apigate | 6873 | ~13746 | 2.22 s | 0 | 237761 |
| items | APISIX | 6506 | ~13011 | 1.15 s | 0.04% | 295934 |
| items | Kong | 6825 | ~13651 | 1.04 s | 0 | 349690 |
| items | Python | 3203 | ~6407 | 1.05 s | 0 | 13263 |
| my-items | apigate | 4540 | ~9080 | 1.30 s | 0 | 74628 |
| my-items | APISIX | 3466 | ~6932 | 1.12 s | 0 | 27742 |
| my-items | Kong | 3215 | ~6430 | 1.14 s | 0 | 23746 |
| my-items | Python | 1596 | ~3192 | 1.19 s | 0 | 230 |
| search | apigate | 6313 | ~12627 | 1.61 s | 0 | 216359 |
| search | APISIX | 5702 | ~11405 | 1.01 s | 0 | 146366 |
| search | Kong | 5215 | ~10430 | 1.09 s | 0 | 127822 |
| search | Python | 2564 | ~5127 | 1.10 s | 0 | 3614 |
| lookup | apigate | 6284 | ~12567 | 1.23 s | 0 | 309170 |
| lookup | APISIX | 5152 | ~10304 | 1.01 s | 0 | 111372 |
| lookup | Kong | 5263 | ~10526 | 1.05 s | 0 | 132992 |
| lookup | Python | 2863 | ~5725 | 1.07 s | 0 | 11388 |

### stress - 9000 RPS x 1 min

| Route | Gateway | RPS | p99 | err | CPU avg | Mem peak |
|---|---|---:|---:|---:|---:|---:|
| items | apigate | 8911 | 210.7 ms | 0 | 67% | 687 MiB |
| items | APISIX | 8701 | 288.7 ms | 0 | 102% | 216 MiB |
| items | Kong | 8501 | 342.6 ms | 0 | 96% | 622 MiB |
| items | Python | 3671 | 60.00 s | 1.51% | 119% | 382 MiB |
| my-items | apigate | 4650 | 7.80 s | 12.16% | 160% | 956 MiB |
| my-items | APISIX | 3813 | 8.38 s | 2.29% | 180% | 458 MiB |
| my-items | Kong | 3525 | 10.27 s | 3.28% | 182% | 854 MiB |
| my-items | Python | 2690 | 60.00 s | 2.37% | 167% | 393 MiB |
| search | apigate | 8744 | 276.1 ms | 0 | 70% | 854 MiB |
| search | APISIX | 8188 | 460.1 ms | 0 | 115% | 311 MiB |
| search | Kong | 8177 | 524.6 ms | 0 | 110% | 737 MiB |
| search | Python | 3260 | 60.00 s | 1.79% | 135% | 393 MiB |
| lookup | apigate | 8811 | 261.4 ms | 0 | 69% | 764 MiB |
| lookup | APISIX | 8145 | 443.5 ms | 0 | 121% | 299 MiB |
| lookup | Kong | 7955 | 676.0 ms | 0 | 111% | 728 MiB |
| lookup | Python | 3430 | 60.00 s | 1.70% | 141% | 385 MiB |

## Findings

- apigate has the lowest p99 in every steady scenario.
- APISIX is consistently lower-latency than Kong in steady and stress, and uses much less memory.
- Python is acceptable at steady `items`, but saturates hard under stress and on validation/auth routes.
- Direct `data` shows the backend is not the primary ramp bottleneck for `items`, `search`, or `lookup`; apigate still has 44-55% lower ramp capacity than direct data on those routes.
- `/my-items` stress is not a clean gateway-only comparison: auth-service, data-service, and gateway share the same 4 vCPUs. The direct data baseline confirms `data-service` alone is not the limiting part of that path.
- No gateway container shows CFS throttling in resource summaries; bottlenecks are application/system capacity, not Docker CPU quota.
