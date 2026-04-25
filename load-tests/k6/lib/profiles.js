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
        preAllocatedVUs: intEnv('RAMP_VUS', 1500),
        maxVUs: intEnv('RAMP_MAX_VUS', 6000),
        stages: [
            { duration: __ENV.RAMP_DURATION || '5m', target: intEnv('RAMP_END', 10000) },
        ],
    }),

    // Stress: well above the expected ceiling — observe how the gateway degrades.
    stress: () => ({
        executor: 'constant-arrival-rate',
        rate: intEnv('STRESS_RPS', 12000),
        timeUnit: '1s',
        duration: __ENV.STRESS_DURATION || '1m',
        preAllocatedVUs: intEnv('STRESS_VUS', 2000),
        maxVUs: intEnv('STRESS_MAX_VUS', 8000),
    }),
};

export const profileNames = Object.keys(profiles);

// Per-profile thresholds, co-located with the registry above so all
// profile-coupled knobs live in one file.
//   ramp aborts on either signal:
//     - p99 > 1 s — quality has degraded past usable.
//     - failure rate > 5 % — gateway is dropping connections / timing out.
//   The failure-rate threshold catches breakdowns that p99 misses: k6
//   evaluates p99 globally over the whole run, so a flood of timeouts
//   late in the ramp is averaged out by the fast samples from earlier.
//   delayAbortEval skips the first 15 s so connection-setup spikes don't
//   trip either threshold prematurely.
export const thresholds = {
    steady: { http_req_failed: [{ threshold: 'rate<0.01', abortOnFail: false }] },
    ramp: {
        http_req_failed:   [{ threshold: 'rate<0.05',  abortOnFail: true, delayAbortEval: '15s' }],
        http_req_duration: [{ threshold: 'p(99)<1000', abortOnFail: true, delayAbortEval: '15s' }],
    },
    stress: {},
};
