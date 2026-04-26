#!/usr/bin/env bash
set -euo pipefail

# Linux: nproc. macOS: sysctl. Fallback: 1.
WORKERS="${GRANIAN_WORKERS:-$(nproc 2>/dev/null || sysctl -n hw.ncpu 2>/dev/null || echo 1)}"

exec granian \
  --interface asgi \
  --host 127.0.0.1 \
  --port 8000 \
  --workers "$WORKERS" \
  --backlog 4096 \
  --runtime-mode st \
  --loop rloop \
  apigate_bench.gateway:app
