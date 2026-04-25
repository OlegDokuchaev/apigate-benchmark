#!/usr/bin/env python3
"""Fetch per-container resource stats from cAdvisor for a benchmark run.

cAdvisor continuously samples every container once per `housekeeping_interval`
and buffers the last `storage_duration` worth of samples in memory. This
script runs *after* a k6 iteration finishes, makes one HTTP request per
container for that buffer, clips it to the [start, end] window, and writes
a JSON report with per-container min/avg/p50/p95/p99/max aggregates for
CPU%, memory, plus network and CFS-throttled-time deltas, computed after
dropping the first `--warmup` seconds of each series.

Compared with polling `docker stats` from a sidecar, this removes the live
measurement process during the k6 run — cAdvisor does the sampling, we
pull it all in one shot when the iteration is done.

Usage:
    collect_resources.py \\
        --cadvisor URL --start UNIX_TS --end UNIX_TS \\
        --warmup SECONDS --json PATH \\
        CONTAINER [CONTAINER ...]
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import urllib.request
from datetime import datetime
from itertools import pairwise
from typing import Any, Callable, NamedTuple, Sequence


class Sample(NamedTuple):
    ts: float                 # unix epoch seconds
    cpu_pct: float            # per-core %; 400 = four cores saturated
    mem_bytes: int            # working_set — cgroup `usage - inactive_file`
    mem_rss_bytes: int        # raw RSS from cgroup stats
    cache_bytes: int          # page-cache pages held by the container
    net_rx_bytes: int         # cumulative counter (all interfaces)
    net_tx_bytes: int         # cumulative counter (all interfaces)
    cpu_throttled_ns: int     # cumulative CFS throttled time


_STAT_KEYS = ('min', 'avg', 'p50', 'p95', 'p99', 'max')

# cAdvisor housekeeping is 1 s in our compose config; 1800 covers a 30-min
# matrix cell with plenty of headroom. Override with --count if needed.
_DEFAULT_COUNT = 1800
_HTTP_TIMEOUT_S = 10.0


# -- parsing -------------------------------------------------------------------

def _parse_iso(ts: str) -> float:
    """cAdvisor emits RFC3339Nano. Python's datetime stops at microseconds,
    so truncate any sub-microsecond digits before parsing."""
    if ts.endswith('Z'):
        ts = ts[:-1] + '+00:00'
    if '.' in ts:
        head, rest = ts.split('.', 1)
        i = 0
        while i < len(rest) and rest[i].isdigit():
            i += 1
        # rest[:i] are fractional-second digits, rest[i:] is the timezone part.
        ts = f'{head}.{rest[:min(i, 6)]}{rest[i:]}'
    return datetime.fromisoformat(ts).timestamp()


def _resolve_id(name: str) -> str | None:
    """Resolve a docker container name to its full ID (cAdvisor keys by ID)."""
    try:
        out = subprocess.check_output(
            ['docker', 'inspect', '--format', '{{.Id}}', name],
            text=True, stderr=subprocess.DEVNULL,
        ).strip()
        return out or None
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def _fetch_raw(cadvisor: str, container_id: str, count: int) -> list[dict[str, Any]]:
    """GET /api/v2.1/stats/docker/<id>?count=N — chronological list of samples."""
    url = f'{cadvisor.rstrip("/")}/api/v2.1/stats/docker/{container_id}?count={count}'
    try:
        with urllib.request.urlopen(url, timeout=_HTTP_TIMEOUT_S) as resp:
            data = json.loads(resp.read().decode())
    except (OSError, json.JSONDecodeError) as e:
        # OSError is the parent of URLError, HTTPError, TimeoutError and
        # the socket errors — one clause covers every transport failure.
        raise RuntimeError(f'cAdvisor at {url}: {e}') from e

    # Handle every shape cAdvisor has shipped for this endpoint:
    #   v2.1:   {"<cgroup_path>": {"spec": {...}, "stats": [samples]}}
    #   older:  {"<cgroup_path>": [samples]}
    #   direct: [samples]
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and data:
        entry = next(iter(data.values()))
        if isinstance(entry, list):
            return entry
        if isinstance(entry, dict):
            return entry.get('stats') or []
    return []


def _sum_network(net: dict[str, Any]) -> tuple[int, int]:
    """Prefer top-level rx/tx_bytes when cAdvisor populates them, else sum
    the per-interface entries. Adding both would double-count on versions
    that populate the primary interface in both places."""
    rx = int(net.get('rx_bytes') or 0)
    tx = int(net.get('tx_bytes') or 0)
    if rx or tx:
        return rx, tx
    for iface in net.get('interfaces') or []:
        rx += int(iface.get('rx_bytes') or 0)
        tx += int(iface.get('tx_bytes') or 0)
    return rx, tx


def _to_samples(raw: list[dict[str, Any]]) -> list[Sample]:
    """Raw cAdvisor entries → Sample records.

    CPU is a monotonic nanosecond counter, so the per-core percent at each
    sample is computed against the previous one. `pairwise` naturally drops
    the first raw entry since it has no baseline.
    """
    parsed = [(_parse_iso(e['timestamp']), e) for e in raw]
    out: list[Sample] = []
    for (prev_ts, prev), (ts, cur) in pairwise(parsed):
        mem = cur.get('memory') or {}
        rx, tx = _sum_network(cur.get('network') or {})
        cpu_total = cur.get('cpu', {}).get('usage', {}).get('total', 0)
        prev_cpu = prev.get('cpu', {}).get('usage', {}).get('total', 0)
        throttled = cur.get('cpu', {}).get('cfs', {}).get('throttled_time', 0)

        dt_ns = (ts - prev_ts) * 1e9
        # Clamp to 0 — a counter reset (container restart mid-window) would
        # otherwise show up as a large negative spike.
        cpu_pct = max(0.0, (cpu_total - prev_cpu) / dt_ns * 100.0) if dt_ns > 0 else 0.0

        out.append(Sample(
            ts=ts, cpu_pct=cpu_pct,
            mem_bytes=int(mem.get('working_set') or mem.get('usage') or 0),
            mem_rss_bytes=int(mem.get('rss') or 0),
            cache_bytes=int(mem.get('cache') or 0),
            net_rx_bytes=rx, net_tx_bytes=tx,
            cpu_throttled_ns=int(throttled or 0),
        ))
    return out


# -- aggregation ---------------------------------------------------------------

def _round3(x: float) -> float:
    return round(x, 3)


def _quantile_sorted(xs: list[float], q: float) -> float:
    idx = (len(xs) - 1) * q
    lo = int(idx)
    hi = min(lo + 1, len(xs) - 1)
    return xs[lo] * (1 - (idx - lo)) + xs[hi] * (idx - lo)


def stats(values: Sequence[float], fmt: Callable[[float], float] = _round3) -> dict[str, float]:
    """Min/avg/p50/p95/p99/max of `values`, post-processed through `fmt`.

    Empty input returns zeroed stats so JSON shape stays stable. Pass
    `fmt=int` for byte counters; default rounds to 3 decimals.
    """
    if not values:
        z = fmt(0)
        return {k: z for k in _STAT_KEYS}
    srt = sorted(values)
    return {
        'min': fmt(srt[0]),
        'avg': fmt(sum(srt) / len(srt)),
        'p50': fmt(_quantile_sorted(srt, 0.50)),
        'p95': fmt(_quantile_sorted(srt, 0.95)),
        'p99': fmt(_quantile_sorted(srt, 0.99)),
        'max': fmt(srt[-1]),
    }


def _aggregate(samples: list[Sample]) -> dict[str, Any]:
    cpu = [s.cpu_pct for s in samples]
    mem = [s.mem_bytes for s in samples]
    rx = [s.net_rx_bytes for s in samples]
    tx = [s.net_tx_bytes for s in samples]
    throttle = [s.cpu_throttled_ns for s in samples]

    # Network counters and CFS throttling are cumulative; delta over the
    # window is what the benchmark actually caused.
    return {
        'samples': len(samples),
        'cpu_pct': stats(cpu),
        'mem_bytes': stats(mem, fmt=int),
        'net_rx_bytes': (max(rx) - min(rx)) if rx else 0,
        'net_tx_bytes': (max(tx) - min(tx)) if tx else 0,
        'cpu_throttled_ms': round((max(throttle) - min(throttle)) / 1e6, 3) if throttle else 0.0,
    }


# -- output --------------------------------------------------------------------

def _fmt_mib(n: float) -> str:
    return f'{n / (1024 * 1024):.1f} MiB'


def _print_summary(containers: dict[str, dict[str, Any]], window_s: float, warmup_s: float) -> None:
    total = sum(c['samples'] for c in containers.values())
    print(
        f'[resources] window={window_s:.1f}s samples={total} warmup={warmup_s:.1f}s',
        file=sys.stderr,
    )
    for name, c in containers.items():
        cpu = c['cpu_pct']
        print(
            f'[resources] {name:<28} '
            f'cpu avg={cpu["avg"]:>6.1f}% p95={cpu["p95"]:>6.1f}% max={cpu["max"]:>6.1f}%  '
            f'mem peak={_fmt_mib(c["mem_bytes"]["max"]):>10}  '
            f'throttled={c["cpu_throttled_ms"]:>6.1f}ms',
            file=sys.stderr,
        )


# -- main ----------------------------------------------------------------------

def _collect_one(cadvisor: str, name: str, count: int,
                 start: float, end: float) -> list[Sample]:
    cid = _resolve_id(name)
    if not cid:
        print(f'warn: container {name!r} not found — skipped', file=sys.stderr)
        return []
    try:
        raw = _fetch_raw(cadvisor, cid, count)
    except RuntimeError as e:
        print(f'warn: {name}: {e}', file=sys.stderr)
        return []
    return [s for s in _to_samples(raw) if start <= s.ts <= end]


def _parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser()
    ap.add_argument('--cadvisor', required=True,
                    help='Base URL of the cAdvisor HTTP endpoint (e.g. http://localhost:8099).')
    ap.add_argument('--start', required=True, type=float, help='Unix timestamp of k6 run start.')
    ap.add_argument('--end', required=True, type=float, help='Unix timestamp of k6 run end.')
    ap.add_argument('--warmup', type=float, default=3.0,
                    help='Seconds to drop from the start of each series (default: 3).')
    ap.add_argument('--count', type=int, default=_DEFAULT_COUNT,
                    help=f'Max samples to request per container (default: {_DEFAULT_COUNT}).')
    ap.add_argument('--json', required=True, help='Output path for aggregated JSON.')
    ap.add_argument('--quiet', action='store_true',
                    help='Do not print a summary to stderr.')
    ap.add_argument('containers', nargs='+', help='Docker container names to collect.')
    return ap.parse_args()


def main() -> int:
    args = _parse_args()

    per_container: dict[str, list[Sample]] = {
        name: _collect_one(args.cadvisor, name, args.count, args.start, args.end)
        for name in args.containers
    }

    cutoff = args.start + args.warmup
    containers: dict[str, dict[str, Any]] = {}
    for name, samples in per_container.items():
        # If everything sits inside the warmup (ultra-short run), fall back
        # to the full series rather than reporting zeros.
        kept = [s for s in samples if s.ts >= cutoff] or samples
        containers[name] = _aggregate(kept)

    window_s = max(args.end - args.start, 0.0)
    out = {
        'window_s': round(window_s, 3),
        'warmup_s': args.warmup,
        'sample_count': sum(c['samples'] for c in containers.values()),
        'containers': containers,
    }
    with open(args.json, 'w') as f:
        json.dump(out, f, indent=2)
        f.write('\n')

    if not args.quiet:
        _print_summary(containers, window_s, args.warmup)

    return 0


if __name__ == '__main__':
    sys.exit(main())
