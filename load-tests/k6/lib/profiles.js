// Load profiles. All open-model (constant/ramping-arrival-rate) so RPS stays
// pinned and latency reflects the gateway's state, not VU saturation.
// Every knob is overridable via an env var of the same uppercase name.

const intEnv = (k, def) => parseInt(__ENV[k] ?? String(def), 10);

export const profiles = {
    // Steady: comfortable RPS for 2 min — p50 / p95 / p99 in steady state.
    steady: () => ({
        executor: 'constant-arrival-rate',
        rate: intEnv('STEADY_RPS', 1500),
        timeUnit: '1s',
        duration: __ENV.STEADY_DURATION || '2m',
        preAllocatedVUs: intEnv('STEADY_VUS', 400),
        maxVUs: intEnv('STEADY_MAX_VUS', 1500),
    }),

    // Ramp: 0 → target over N minutes — locate the saturation point.
    ramp: () => ({
        executor: 'ramping-arrival-rate',
        startRate: intEnv('RAMP_START', 0),
        timeUnit: '1s',
        preAllocatedVUs: intEnv('RAMP_VUS', 1000),
        maxVUs: intEnv('RAMP_MAX_VUS', 4000),
        stages: [
            { duration: __ENV.RAMP_DURATION || '5m', target: intEnv('RAMP_END', 6000) },
        ],
    }),

    // Stress: well above the expected ceiling — observe how the gateway degrades.
    stress: () => ({
        executor: 'constant-arrival-rate',
        rate: intEnv('STRESS_RPS', 8000),
        timeUnit: '1s',
        duration: __ENV.STRESS_DURATION || '1m',
        preAllocatedVUs: intEnv('STRESS_VUS', 1500),
        maxVUs: intEnv('STRESS_MAX_VUS', 5000),
    }),
};

export const profileNames = Object.keys(profiles);
