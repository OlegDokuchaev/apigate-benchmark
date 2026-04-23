import http from 'k6/http';
import { check, fail } from 'k6';
import { profiles } from './lib/profiles.js';
import { routes } from './lib/routes.js';
import { summary } from './lib/summary.js';

const ROUTE = __ENV.ROUTE || 'items';
const PROFILE = __ENV.PROFILE || 'steady';
const GATEWAY_URL = __ENV.GATEWAY_URL || 'http://localhost:8080';
const AUTH_URL = __ENV.AUTH_URL || 'http://localhost:8001';
const GATEWAY_NAME = __ENV.GATEWAY_NAME || 'unknown';

if (!routes[ROUTE]) fail(`unknown ROUTE=${ROUTE}`);
if (!profiles[PROFILE]) fail(`unknown PROFILE=${PROFILE}`);

// Thresholds are enabled only for `steady`: ramp and stress deliberately push
// the gateway out of the green zone, so an assert-style threshold there just
// turns the run into a pass/fail guessing game.
const thresholds = PROFILE === 'steady'
    ? { http_req_failed: [{ threshold: 'rate<0.01', abortOnFail: false }] }
    : {};

export const options = {
    scenarios: { [PROFILE]: profiles[PROFILE]() },
    thresholds,
    // One k6 run = one route × one profile × one gateway, so every metric can
    // safely carry these as global tags instead of per-request ones.
    tags: { profile: PROFILE, gateway: GATEWAY_NAME, route: ROUTE },
    discardResponseBodies: true,
    summaryTrendStats: ['avg', 'min', 'med', 'p(90)', 'p(95)', 'p(99)', 'max'],
};

// Register the user (ignore 409 — already exists), log in, return the token.
// The token is only needed for /my-items, but the cost of setup on other runs
// is near-zero, so we keep a single code path.
export function setup() {
    if (ROUTE !== 'my-items') return { token: null };

    const creds = JSON.stringify({ email: 'loadtest@example.com', password: 'hunter22' });
    const opts = { headers: { 'content-type': 'application/json' }, responseType: 'text' };

    http.post(`${AUTH_URL}/register`, creds, opts);
    const res = http.post(`${AUTH_URL}/login`, creds, opts);
    if (res.status !== 200) fail(`login failed: ${res.status} ${res.body}`);
    const token = res.json('access_token');
    if (!token) fail(`no access_token in response: ${res.body}`);
    return { token };
}

export default function (data) {
    const res = routes[ROUTE](GATEWAY_URL, data.token);
    check(res, { '2xx': (r) => r.status >= 200 && r.status < 300 });
}

export function handleSummary(data) {
    return summary(data, { gateway: GATEWAY_NAME, route: ROUTE, profile: PROFILE });
}
