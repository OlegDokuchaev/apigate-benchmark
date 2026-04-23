// One function per public gateway route. A k6 run invokes exactly one of
// these per iteration (driven by the ROUTE env in scenario.js).
// The `route` metric tag is set globally in scenario.js — no need to repeat
// it per request.

import http from 'k6/http';

const jsonHeaders = { 'content-type': 'application/json' };

// Pre-stringified bodies — avoids re-serializing the same JSON each iteration.
const searchBody = JSON.stringify({ category: 'office', max_price: 300 });
const lookupBody = JSON.stringify({ q: 'pen' });

export const routes = {
    'items':    (gw)        => http.get(`${gw}/items`),
    'my-items': (gw, token) => http.get(`${gw}/my-items`, {
        headers: { authorization: `Bearer ${token}` },
    }),
    'search':   (gw) => http.post(`${gw}/items/search`, searchBody, { headers: jsonHeaders }),
    'lookup':   (gw) => http.post(`${gw}/items/lookup`, lookupBody, { headers: jsonHeaders }),
};

export const routeNames = Object.keys(routes);
