// One function per benchmark route. A k6 run invokes exactly one of these per
// iteration (driven by the ROUTE env in scenario.js).
// The `route` metric tag is set globally in scenario.js — no need to repeat
// it per request.

import http from 'k6/http';

const jsonHeaders = { 'content-type': 'application/json' };
const directUserHeaders = { 'X-User-Id': 'loadtest-user', 'X-User-Email': 'loadtest@example.com' };
const jsonParams = { headers: jsonHeaders };
const directUserParams = { headers: directUserHeaders };

// Pre-stringified bodies — avoids re-serializing the same JSON each iteration.
const searchBody = JSON.stringify({ category: 'office', max_price: 300 });
const publicLookupBody = JSON.stringify({ q: 'pen' });
const internalLookupBody = JSON.stringify({ query: 'pen', limit: 20, source: 'gateway' });

const gatewayRoutes = {
    'items':    (gw) => http.get(`${gw}/items`),
    'my-items': (gw, setupData) => http.get(`${gw}/my-items`, setupData.authParams),
    'search':   (gw) => http.post(`${gw}/items/search`, searchBody, jsonParams),
    'lookup':   (gw) => http.post(`${gw}/items/lookup`, publicLookupBody, jsonParams),
};

const directDataRoutes = {
    'items':    (gw) => http.get(`${gw}/items`),
    'my-items': (gw) => http.get(`${gw}/my-items`, directUserParams),
    'search':   (gw) => http.post(`${gw}/items/search`, searchBody, jsonParams),
    'lookup':   (gw) => http.post(`${gw}/items/lookup`, internalLookupBody, jsonParams),
};

export function selectRoutes(targetMode) {
    return targetMode === 'direct-data' ? directDataRoutes : gatewayRoutes;
}

export const routeNames = Object.keys(gatewayRoutes);
