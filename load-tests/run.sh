#!/usr/bin/env bash
# Runs the profile × route matrix against a single gateway.
# Usage:
#   ./run.sh <gateway-name> <gateway-url>
#   ./run.sh apigate  http://localhost:8080
#   ./run.sh kong     http://localhost:8090
#   ./run.sh python   http://localhost:8092
#
# Override profile defaults via env, e.g.:
#   STEADY_RPS=800 STRESS_RPS=4000 ./run.sh apigate http://localhost:8080
#
# Cooldown between runs is overridable:
#   COOLDOWN=60 ./run.sh apigate http://localhost:8080
#
# Run one gateway at a time — stop the others so they don't share CPU.

set -euo pipefail

GATEWAY_NAME=${1:-apigate}
GATEWAY_URL=${2:-http://localhost:8080}
AUTH_URL=${AUTH_URL:-http://localhost:8001}
COOLDOWN=${COOLDOWN:-30}

ROUTES=(${ROUTES_OVERRIDE:-items my-items search lookup})
PROFILES=(${PROFILES_OVERRIDE:-steady ramp stress})

cd "$(dirname "$0")"
mkdir -p results

if ! command -v k6 >/dev/null 2>&1; then
    echo "error: k6 not found on PATH" >&2
    exit 1
fi

echo "gateway: $GATEWAY_NAME ($GATEWAY_URL)"
echo "auth:    $AUTH_URL"
echo "matrix:  profiles=[${PROFILES[*]}] routes=[${ROUTES[*]}]"
echo

for profile in "${PROFILES[@]}"; do
    for route in "${ROUTES[@]}"; do
        echo "=================================================="
        echo ">>> $GATEWAY_NAME / $route / $profile"
        echo "=================================================="
        k6 run \
            -e GATEWAY_NAME="$GATEWAY_NAME" \
            -e GATEWAY_URL="$GATEWAY_URL" \
            -e AUTH_URL="$AUTH_URL" \
            -e ROUTE="$route" \
            -e PROFILE="$profile" \
            k6/scenario.js
        echo
        # Give upstreams and the gateway a moment to drain (TIME_WAIT after stress).
        sleep "$COOLDOWN"
    done
done

echo "done. results/ contains per-run JSON summaries."
