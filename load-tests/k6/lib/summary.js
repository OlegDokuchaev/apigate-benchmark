import { textSummary } from 'https://jslib.k6.io/k6-summary/0.0.2/index.js';

export function summary(data, meta) {
    const filename = `results/${meta.gateway}_${meta.route}_${meta.profile}.json`;
    return {
        stdout: textSummary(data, { indent: ' ', enableColors: true }),
        [filename]: JSON.stringify({ meta, metrics: data.metrics }, null, 2),
    };
}
