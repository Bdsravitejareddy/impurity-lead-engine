# Crawler execution validation

The deterministic benchmark uses the real adapters, host gate, retry policy, scoring, contact verification, publication serialization, and exports with simulated HTTP latency and an in-memory task store. It runs five repetitions for serial and six-worker execution, compares normalized outputs, and reports task and retry counts:

```text
serial median: 1.8725s
six-worker median: 0.7531s
speedup: 2.49x
tasks: 29 per run
attempts: 41 per run
retries: 12 per run
requests: 146 per run
outputs_equal: true
```

These timings do not measure Supabase latency, internet variability, or production throughput. The PostgreSQL integration suite uses a disposable local PostgreSQL instance (or the dedicated localhost `impurity_test` CI service) and exercises atomic claims, coordinator exclusion, leases, fencing, retries, cooldowns, payload guards, publication rollback, RLS, resume, and idempotent reruns.
