#!/usr/bin/env python3
"""Benchmark the real durable stage graph with deterministic offline HTTP/DB doubles."""
import argparse
import hashlib
import json
from pathlib import Path
import statistics
import sys
import tempfile
import time


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from execution.workload import Workload, fixed_clock


def benchmark(repetitions=5, domains=12, latency=.01):
    if repetitions < 5:
        raise ValueError("at least five repetitions are required")
    samples = {1: [], 6: []}
    counts = {1: [], 6: []}
    expected = None
    with tempfile.TemporaryDirectory(prefix="crawl-benchmark-") as directory, fixed_clock():
        for repetition in range(repetitions):
            # Alternate order to reduce warm-up/order bias.
            for workers in ((1, 6) if repetition % 2 == 0 else (6, 1)):
                workload = Workload(domains=domains, latency=latency)
                try:
                    started = time.perf_counter()
                    result = workload.execute(Path(directory) / f"{repetition}-{workers}", workers)
                    elapsed = time.perf_counter() - started
                    if result != 0:
                        raise RuntimeError("offline benchmark did not complete")
                    output = workload.outputs()
                    if expected is None:
                        expected = output
                    if output != expected:
                        raise AssertionError("business output changed across worker counts or repetitions")
                    samples[workers].append(elapsed)
                    counts[workers].append(workload.counts())
                finally:
                    workload.close()
    if any(count != counts[1][0] for group in counts.values() for count in group):
        raise AssertionError("task, retry, or request counts changed")
    medians = {workers: statistics.median(values) for workers, values in samples.items()}
    return {"repetitions_per_worker_count": repetitions, "domains": domains,
            "simulated_request_latency_seconds": latency, "samples_seconds": samples,
            "median_seconds": medians, "speedup": medians[1] / medians[6],
            "counts_per_run": counts[1][0], "outputs_equal": True,
            "output_sha256": hashlib.sha256(json.dumps(expected, sort_keys=True).encode()).hexdigest(),
            "limitations": "MockTransport network and in-memory database; real adapters, host gating, retries, scoring, contacts, publication serialization and exports. Does not measure Supabase/network variability or production throughput."}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repetitions", type=int, default=5)
    parser.add_argument("--domains", type=int, default=12)
    parser.add_argument("--latency", type=float, default=.01)
    arguments = parser.parse_args()
    print(json.dumps(benchmark(arguments.repetitions, arguments.domains, arguments.latency), indent=2))
