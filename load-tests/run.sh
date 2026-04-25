#!/usr/bin/env bash
# Runs the profile × route matrix against a single gateway. When cAdvisor is
# reachable, pulls per-container CPU / memory / network after each k6 run.
#
# Usage:
#   ./run.sh <gateway-name> <gateway-url>
#   ./run.sh apigate  http://localhost:8080
#   ./run.sh kong     http://localhost:8090
#   ./run.sh python   http://localhost:8092
#
# Override profile defaults via env:
#   STEADY_RPS=800 STRESS_RPS=4000 ./run.sh apigate http://localhost:8080
#
# Resource-collection env:
#   SAMPLE_RESOURCES=0   skip cAdvisor collection entirely
#   CADVISOR_URL=...     default http://localhost:8099
#   WARMUP=5             seconds to drop from the start of each sample series
#   COOLDOWN=60          seconds between runs (TIME_WAIT drain)
#
# Run one gateway at a time — stop the others so they don't share CPU.

set -euo pipefail

GATEWAY_NAME=${1:-apigate}
GATEWAY_URL=${2:-http://localhost:8080}
AUTH_URL=${AUTH_URL:-http://localhost:8001}
CADVISOR_URL=${CADVISOR_URL:-http://localhost:8099}
COOLDOWN=${COOLDOWN:-30}
WARMUP=${WARMUP:-3}
SAMPLE_RESOURCES=${SAMPLE_RESOURCES:-1}

ROUTES=(${ROUTES_OVERRIDE:-items my-items search lookup})
PROFILES=(${PROFILES_OVERRIDE:-steady ramp stress})

cd "$(dirname "$0")"
mkdir -p results

if ! command -v k6 >/dev/null 2>&1; then
    echo "error: k6 not found on PATH" >&2
    exit 1
fi

# Map CLI gateway name → docker-compose service name.
case "$GATEWAY_NAME" in
    apigate) GATEWAY_SERVICE=gateway-apigate ;;
    kong)    GATEWAY_SERVICE=gateway-kong    ;;
    python)  GATEWAY_SERVICE=gateway-python  ;;
    *)       GATEWAY_SERVICE=gateway-$GATEWAY_NAME ;;
esac

# -- discovery ----------------------------------------------------------------

# Resolve a compose service to the running container name via its label.
find_container() {
    docker ps \
        --filter "label=com.docker.compose.service=$1" \
        --filter "status=running" \
        --format '{{.Names}}' 2>/dev/null | head -n1
}

# Probe cAdvisor's /healthz via stdlib urllib so we don't require curl.
cadvisor_probe() {
    python3 - "$1" <<'PY' 2>/dev/null
import sys, urllib.request
urllib.request.urlopen(sys.argv[1] + '/healthz', timeout=2).read()
PY
}

# Retry briefly: `docker compose up -d cadvisor` returns before cAdvisor's
# HTTP server is listening, so a tight follow-up `run.sh` hits a cold probe.
cadvisor_ok() {
    for _ in 1 2 3; do
        cadvisor_probe "$1" && return 0
        sleep 1
    done
    return 1
}

SAMPLE_TARGETS=()
if [[ "$SAMPLE_RESOURCES" == "1" ]]; then
    if ! command -v docker >/dev/null 2>&1; then
        echo "note: docker not on PATH — skipping resource collection"
        SAMPLE_RESOURCES=0
    elif ! command -v python3 >/dev/null 2>&1; then
        echo "note: python3 not on PATH — skipping resource collection"
        SAMPLE_RESOURCES=0
    elif ! cadvisor_ok "$CADVISOR_URL"; then
        echo "note: cAdvisor not reachable at $CADVISOR_URL — skipping resource collection"
        echo "      (start it with: docker compose up -d cadvisor)"
        SAMPLE_RESOURCES=0
    else
        # `cadvisor` last so the measurer's own footprint shows up in the report.
        for svc in "$GATEWAY_SERVICE" auth data cadvisor; do
            name=$(find_container "$svc" || true)
            [[ -n "$name" ]] && SAMPLE_TARGETS+=("$name")
        done
        if [[ ${#SAMPLE_TARGETS[@]} -eq 0 ]]; then
            echo "note: no running compose containers for '$GATEWAY_SERVICE' — skipping resource collection"
            SAMPLE_RESOURCES=0
        fi
    fi
fi

# -- per-cell runner ----------------------------------------------------------

collect_resources() {
    local start=$1 end=$2 json=$3
    [[ "$SAMPLE_RESOURCES" == "1" ]] || return 0
    # Give cAdvisor's 1 s housekeeping tick time to capture the tail of the run.
    sleep 2
    python3 scripts/collect_resources.py \
        --cadvisor "$CADVISOR_URL" \
        --start "$start" --end "$end" \
        --warmup "$WARMUP" \
        --json "$json" \
        "${SAMPLE_TARGETS[@]}" || true
}

run_cell() {
    local profile=$1 route=$2
    local key=${GATEWAY_NAME}_${route}_${profile}
    local res_json=results/${key}_resources.json

    echo "=================================================="
    echo ">>> $GATEWAY_NAME / $route / $profile"
    echo "=================================================="

    local start_ts=$(date +%s)

    local k6_rc=0
    k6 run \
        -e GATEWAY_NAME="$GATEWAY_NAME" \
        -e GATEWAY_URL="$GATEWAY_URL" \
        -e AUTH_URL="$AUTH_URL" \
        -e ROUTE="$route" \
        -e PROFILE="$profile" \
        k6/scenario.js || k6_rc=$?

    local end_ts=$(date +%s)

    collect_resources "$start_ts" "$end_ts" "$res_json"

    if [[ "$k6_rc" -ne 0 ]]; then
        echo "warn: k6 exited $k6_rc"
    fi
}

# -- main loop ----------------------------------------------------------------

echo "gateway:  $GATEWAY_NAME ($GATEWAY_URL)"
echo "auth:     $AUTH_URL"
echo "matrix:   profiles=[${PROFILES[*]}] routes=[${ROUTES[*]}]"
if [[ "$SAMPLE_RESOURCES" == "1" ]]; then
    echo "cadvisor: $CADVISOR_URL containers=[${SAMPLE_TARGETS[*]}] warmup=${WARMUP}s"
else
    echo "cadvisor: disabled"
fi
echo

total=$((${#PROFILES[@]} * ${#ROUTES[@]}))
i=0
for profile in "${PROFILES[@]}"; do
    for route in "${ROUTES[@]}"; do
        run_cell "$profile" "$route"
        echo
        i=$((i + 1))
        # Let upstreams and the gateway drain (TIME_WAIT after stress).
        # Skip on the last cell — nothing follows it.
        if [[ $i -lt $total ]]; then
            sleep "$COOLDOWN"
        fi
    done
done

echo "done. results/ contains:"
echo "  <gateway>_<route>_<profile>.json            — k6 per-run summary"
if [[ "$SAMPLE_RESOURCES" == "1" ]]; then
    echo "  <gateway>_<route>_<profile>_resources.json  — cAdvisor per-container aggregates"
fi
