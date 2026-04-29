import http from 'k6/http';
import { check, fail } from 'k6';
import { profiles, thresholds } from './lib/profiles.js';
import { selectRoutes } from './lib/routes.js';
import { summary } from './lib/summary.js';

const ROUTE = __ENV.ROUTE || 'items';
const PROFILE = __ENV.PROFILE || 'steady';
const GATEWAY_URL = __ENV.GATEWAY_URL || 'http://localhost:8080';
const AUTH_URL = __ENV.AUTH_URL || 'http://localhost:8001';
const GATEWAY_NAME = __ENV.GATEWAY_NAME || 'unknown';
const TARGET_MODE = __ENV.TARGET_MODE || (__ENV.DIRECT_DATA === '1' ? 'direct-data' : 'gateway');

if (!['gateway', 'direct-data'].includes(TARGET_MODE)) fail(`unknown TARGET_MODE=${TARGET_MODE}`);
const routes = selectRoutes(TARGET_MODE);
if (!routes[ROUTE]) fail(`unknown ROUTE=${ROUTE}`);
if (!profiles[PROFILE]) fail(`unknown PROFILE=${PROFILE}`);

export const options = {
    scenarios: { [PROFILE]: profiles[PROFILE]() },
    thresholds: thresholds[PROFILE],
    tags: { profile: PROFILE, gateway: GATEWAY_NAME, route: ROUTE },
    discardResponseBodies: true,
    summaryTrendStats: ['avg', 'min', 'med', 'p(90)', 'p(95)', 'p(99)', 'max'],
};

export function setup() {
    if (TARGET_MODE !== 'gateway' || ROUTE !== 'my-items') return { authParams: null };

    const creds = JSON.stringify({ email: 'loadtest@example.com', password: 'hunter22' });
    const opts = { headers: { 'content-type': 'application/json' }, responseType: 'text' };

    http.post(`${AUTH_URL}/register`, creds, opts);
    const res = http.post(`${AUTH_URL}/login`, creds, opts);
    if (res.status !== 200) fail(`login failed: ${res.status} ${res.body}`);
    const token = res.json('access_token');
    if (!token) fail(`no access_token in response: ${res.body}`);
    return { authParams: { headers: { authorization: `Bearer ${token}` } } };
}

export default function (data) {
    const res = routes[ROUTE](GATEWAY_URL, data);
    check(res, { '2xx': (r) => r.status >= 200 && r.status < 300 });
}

export function handleSummary(data) {
    return summary(data, {
        gateway: GATEWAY_NAME,
        route: ROUTE,
        profile: PROFILE,
        target_mode: TARGET_MODE,
    });
}
