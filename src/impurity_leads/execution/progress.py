"""Read-only durable progress summaries and optional terminal rendering."""

from __future__ import annotations

import json
import os
import re
import sys
import threading
from collections import Counter
from datetime import datetime, timezone
from urllib.parse import urlsplit


STATES = ("pending", "running", "retryable_failed", "completed", "skipped", "permanent_failed")
TERMINAL = frozenset(("completed", "skipped", "permanent_failed"))
COUNTS = frozenset(("records", "signals", "qualified", "contacts"))
ERRORS = frozenset((
    "unknown_error", "http_401", "http_403", "http_404", "http_429", "http_5xx",
    "unauthorized", "forbidden", "not_found", "rate_limited", "server_error",
    "tls_error", "dns_error", "connect_error", "read_timeout", "timeout",
    "network_error", "database_unavailable", "malformed_output", "result_too_large",
    "robots_denied", "robots_401", "robots_403", "attempts_exhausted", "lease_expired", "cancelled",
    "task_timeout", "malformed_response", "response_too_large", "https_downgrade",
    "network_outage", "interrupted", "task_error", "unsupported_scheme", "checkpoint_too_large",
)) | frozenset(f"http_{status}" for status in range(400, 600))


def _time(value):
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if not isinstance(value, datetime):
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and 0 <= value < float("inf")


def summarize(run: dict, tasks: list[dict], now: datetime | None = None) -> dict:
    """Summarize persisted state; terminal failures settle work without counting as success."""
    now = _time(now) or datetime.now(timezone.utc)
    started = _time(run.get("started_at")) or now
    ended = _time(run.get("completed_at")) or now
    counts = Counter(task.get("status") for task in tasks)
    settled = sum(counts[state] for state in TERMINAL)
    active = sum(task.get("status") == "running" and
                 (_time(task.get("lease_expires_at")) or now) > now for task in tasks)
    activity = [started]
    for row in [run, *tasks]:
        for field in ("updated_at", "heartbeat_at", "completed_at", "started_at"):
            value = _time(row.get(field))
            if value is not None:
                activity.append(value)
    provisional = not bool((run.get("config_json") or {}).get("planning_complete") or (run.get("metrics_json") or {}).get("planning_complete"))
    result = {
        "run_id": run.get("id", run.get("run_id")), "status": run.get("status"),
        "age_seconds": max(0, (now - started).total_seconds()),
        "current_stage": run.get("current_stage"),
        "progress_percentage": settled * 100 / len(tasks) if tasks else 0.0,
        "provisional": provisional, "settled": settled, "total": len(tasks),
        **{state: counts[state] for state in STATES},
        "active_leases": active, "workers_active": active,
        "last_activity": max(activity).isoformat(),
        "elapsed_seconds": max(0, (ended - started).total_seconds()),
    }
    provider_usage = (run.get("metrics_json") or {}).get("provider_usage")
    if isinstance(provider_usage, list):
        result["provider_usage"] = [
            {
                "provider": str(row.get("provider") or "unknown")[:80],
                "requests": int(row.get("requests") or 0),
                "jobs": int(row.get("jobs") or 0),
                "estimated_paid_requests": int(row.get("estimated_paid_requests") or 0),
            }
            for row in provider_usage if isinstance(row, dict)
        ]
    samples = [task["duration_seconds"] for task in tasks
               if task.get("status") in TERMINAL and _number(task.get("duration_seconds"))]
    if not provisional and len(samples) >= 3:
        result["eta_seconds"] = sum(samples) / len(samples) * (len(tasks) - settled) / max(1, active)
    for field in COUNTS:
        value = (run.get("metrics_json") or {}).get(field)
        if _number(value):
            result[field] = value
    return result


def _label(value, *, token=False):
    if not isinstance(value, str) or len(value) > 160:
        return None
    # Labels are deliberately small: URLs, control characters and key/value dumps are not labels.
    pattern = r"[a-zA-Z0-9_.:-]+" if token else r"[a-zA-Z0-9 .,&'()_-]+"
    return value if re.fullmatch(pattern, value) else None


def _safe_event(event):
    result = {}
    for field in ("event", "run_id", "stage", "status", "source", "company"):
        value = _label(event.get(field), token=field not in ("company", "source"))
        if value is not None:
            result[field] = value
    if "domain" in event and isinstance(event["domain"], str):
        try:
            parsed = urlsplit(event["domain"] if "://" in event["domain"] else "//" + event["domain"])
            domain = parsed.hostname
            if domain and re.fullmatch(r"[a-zA-Z0-9.-]+", domain):
                result["domain"] = domain.lower()
        except ValueError:
            pass
    if isinstance(event.get("provider_usage"), list):
        result["provider_usage"] = [
            {
                "provider": str(row.get("provider") or "unknown")[:80],
                "requests": max(0, int(row.get("requests") or 0)),
                "jobs": max(0, int(row.get("jobs") or 0)),
                "estimated_paid_requests": max(0, int(row.get("estimated_paid_requests") or 0)),
            }
            for row in event["provider_usage"] if isinstance(row, dict)
        ]
    if event.get("error") is not None:
        value = event["error"]
        result["error"] = value if isinstance(value, str) and value in ERRORS else "unknown_error"
    for field in (*COUNTS, "attempt"):
        if _number(event.get(field)):
            result[field] = event[field]
    return result


class Reporter:
    """Use Rich only for interactive TTYs; otherwise write safe JSON lines."""

    def __init__(self, stream=None, interactive=None, workers=6):
        self.stream = stream if stream is not None else sys.stdout
        self.workers = workers
        self._metrics = {}
        self._lock = threading.Lock()
        self._live = None
        self._last_event = {}
        tty = bool(getattr(self.stream, "isatty", lambda: False)())
        enabled = tty and interactive is not False and not (os.getenv("CI") or os.getenv("GITHUB_ACTIONS"))
        if enabled:
            try:
                from rich.console import Console
                from rich.live import Live
            except ImportError:
                pass
            else:
                self._live = Live("", console=Console(file=self.stream, markup=False), refresh_per_second=4)
                self._live.start()

    def _write(self, event):
        self.stream.write(json.dumps(event, sort_keys=True, allow_nan=False) + "\n")
        self.stream.flush()

    def emit(self, event: dict) -> None:
        safe = _safe_event(event)
        with self._lock:
            self._metrics.update({key: value for key, value in safe.items() if key in COUNTS})
            self._last_event = safe
            if self._live is None:
                self._write(safe)
            else:
                self._live.update(json.dumps(safe, sort_keys=True))

    def render(self, run, tasks) -> None:
        snapshot = summarize(run, tasks)
        # Run metrics are authoritative when present; event metrics fill only missing counts.
        with self._lock:
            configured_workers = (run.get("config_json") or {}).get("workers")
            workers_total = configured_workers if isinstance(configured_workers, int) and configured_workers > 0 else self.workers
            snapshot = {**self._metrics, **snapshot, "workers_total": workers_total, "event": "progress"}
            for field in ("run_id", "status", "current_stage"):
                snapshot[field] = _label(snapshot.get(field), token=True)
            if self._live is None:
                self._write(snapshot)
            else:
                eta = snapshot.get("eta_seconds")
                suffix = " (provisional)" if snapshot["provisional"] else ""
                lines = [f"Run {snapshot['run_id']} | {snapshot['status']} | {snapshot['current_stage']}",
                         f"Progress {snapshot['settled']}/{snapshot['total']} ({snapshot['progress_percentage']:.1f}%){suffix}",
                         f"Workers {snapshot['workers_active']}/{workers_total} | elapsed {snapshot['elapsed_seconds']:.0f}s",
                         " | ".join(f"{state}: {snapshot[state]}" for state in STATES),
                         " | ".join(f"{field}: {snapshot[field]}" for field in sorted(COUNTS) if field in snapshot)]
                if eta is not None:
                    lines.append(f"ETA {eta:.0f}s (estimate)")
                if self._last_event:
                    lines.append(json.dumps(self._last_event, sort_keys=True))
                self._live.update("\n".join(lines))

    def close(self) -> None:
        with self._lock:
            if self._live is not None:
                self._live.stop()
                self._live = None
