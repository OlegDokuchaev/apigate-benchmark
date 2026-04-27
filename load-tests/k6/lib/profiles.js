// Load profiles. All open-model (constant/ramping-arrival-rate) so RPS stays
// pinned and latency reflects the gateway's state, not VU saturation.
// Every knob is overridable via an env var of the same uppercase name.

const intEnv = (k, def) => parseInt(__ENV[k] ?? String(def), 10);

export const profiles = {
    // Steady: comfortable RPS for 2 min — p50 / p95 / p99 in steady state.
    steady: () => ({
        executor: 'constant-arrival-rate',
        rate: intEnv('STEADY_RPS', 2500),
        timeUnit: '1s',
        duration: __ENV.STEADY_DURATION || '2m',
        preAllocatedVUs: intEnv('STEADY_VUS', 500),
        maxVUs: intEnv('STEADY_MAX_VUS', 2000),
    }),

    // Ramp: 0 → target over N minutes — locate the saturation point.
    ramp: () => ({
        executor: 'ramping-arrival-rate',
        startRate: intEnv('RAMP_START', 0),
        timeUnit: '1s',
        preAllocatedVUs: intEnv('RAMP_VUS', 2000),
        maxVUs: intEnv('RAMP_MAX_VUS', 12000),
        stages: [
            { duration: __ENV.RAMP_DURATION || '5m', target: intEnv('RAMP_END', 20000) },
        ],
    }),

    // Stress: above the expected ceiling — observe how the gateway degrades.
    stress: () => ({
        executor: 'constant-arrival-rate',
        rate: intEnv('STRESS_RPS', 10000),
        timeUnit: '1s',
        duration: __ENV.STRESS_DURATION || '1m',
        preAllocatedVUs: intEnv('STRESS_VUS', 2000),
        maxVUs: intEnv('STRESS_MAX_VUS', 10000),
    }),
};

export const profileNames = Object.keys(profiles);

// Per-profile thresholds. Scoped to the scenario tag so setup() requests
// (e.g. /register + /login for my-items) don't dilute the main load metric.
// Scenario name matches PROFILE because options.scenarios is keyed by PROFILE.
//   steady — soft floor: fail the run if >1 % errored (no abort, just exit code).
//   ramp   — soft thresholds: p99 > 3 s or failure rate > 10 %.
//   stress — no thresholds; we want to observe degradation, not assert it.
export const thresholds = {
    steady: {
        'http_req_failed{scenario:steady}': [
            { threshold: 'rate<0.01', abortOnFail: false },
        ],
    },
    ramp: {
        'http_req_failed{scenario:ramp}': [
            { threshold: 'rate<0.05', abortOnFail: true, delayAbortEval: '15s' },
        ],
        'http_req_duration{scenario:ramp}': [
            { threshold: 'p(99)<1000', abortOnFail: true, delayAbortEval: '15s' },
        ],
    },
    stress: {},
};
