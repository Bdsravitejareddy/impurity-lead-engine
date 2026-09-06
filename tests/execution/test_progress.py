import io
import json
import sys
import pytest
from datetime import datetime, timedelta, timezone
from types import ModuleType

from impurity_leads.execution.progress import Reporter, summarize


NOW = datetime(2026, 9, 5, tzinfo=timezone.utc)


def run(**kwargs):
    return {"id": "run-1", "status": "running", "started_at": (NOW - timedelta(seconds=60)).isoformat(),
            "current_stage": "crawl", "config_json": {"planning_complete": True}, **kwargs}


def test_progress_counts_settled_tasks_including_skips_and_failures():
    tasks = [{"status": state, "duration_seconds": 6} for state in
             ("completed", "skipped", "permanent_failed", "retryable_failed", "pending", "running")]
    tasks[-1]["lease_expires_at"] = (NOW + timedelta(seconds=30)).isoformat()
    result = summarize(run(metrics_json={"signals": 4, "qualified": 2, "contacts": 3}), tasks, NOW)
    assert result["progress_percentage"] == 50
    assert result["settled"] == 3
    assert result["completed"] == 1
    assert result["active_leases"] == result["workers_active"] == 1
    assert result["age_seconds"] == result["elapsed_seconds"] == 60
    assert result["signals"] == 4 and result["qualified"] == 2 and result["contacts"] == 3
    assert result["eta_seconds"] >= 0


def test_eta_requires_closed_plan_and_three_duration_samples():
    tasks = [{"status": "completed", "duration_seconds": 6} for _ in range(3)]
    assert summarize(run(config_json={}), tasks, NOW)["provisional"] is True
    assert summarize(run(config_json={}), tasks, NOW).get("eta_seconds") is None
    assert summarize(run(), tasks[:2], NOW).get("eta_seconds") is None
    assert summarize(run(), tasks, NOW)["eta_seconds"] == 0


def test_expired_leases_and_finished_elapsed():
    tasks = [{"status": "running", "lease_expires_at": (NOW - timedelta(seconds=1)).isoformat(),
              "updated_at": (NOW - timedelta(seconds=2)).isoformat()}]
    result = summarize(run(completed_at=(NOW - timedelta(seconds=10)).isoformat()), tasks, NOW)
    assert result["active_leases"] == 0
    assert result["elapsed_seconds"] == 50
    assert result["last_activity"] == tasks[0]["updated_at"]


def test_json_events_only_include_safe_fields_and_categories():
    stream = io.StringIO()
    reporter = Reporter(stream=stream)
    reporter.emit({"event": "task_failed", "run_id": "run-1", "company": "Example Pharma",
                   "domain": "https://example.com/path?api_key=secret", "error": "password=secret",
                   "headers": {"Authorization": "secret"}, "exception": RuntimeError("secret"),
                   "status": "retryable_failed", "attempt": 2})
    result = json.loads(stream.getvalue())
    assert result["company"] == "Example Pharma"
    assert result["domain"] == "example.com"
    assert result["error"] == "unknown_error"
    assert result["attempt"] == 2
    assert "secret" not in stream.getvalue()
    assert "headers" not in result and "exception" not in result


def test_non_tty_snapshot_is_json_and_merges_safe_output_metrics():
    stream = io.StringIO()
    reporter = Reporter(stream=stream)
    reporter.emit({"event": "scored", "signals": 5, "qualified": 2, "contacts": 1})
    reporter.render(run(), [])
    reporter.close()
    result = json.loads(stream.getvalue().splitlines()[-1])
    assert result["event"] == "progress"
    assert result["signals"] == 5
    assert result["workers_total"] == 6


def test_tty_rich_lifecycle_and_ci_fallback(monkeypatch):
    class TTY(io.StringIO):
        def isatty(self):
            return True

    instances = []

    class Live:
        def __init__(self, *args, **kwargs):
            self.updated = []
            self.stopped = False
            instances.append(self)

        def start(self):
            pass

        def update(self, renderable):
            self.updated.append(renderable)

        def stop(self):
            self.stopped = True

    live_module = ModuleType("rich.live")
    live_module.Live = Live
    console_module = ModuleType("rich.console")
    console_module.Console = lambda **kwargs: object()
    monkeypatch.setitem(sys.modules, "rich.live", live_module)
    monkeypatch.setitem(sys.modules, "rich.console", console_module)
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    reporter = Reporter(stream=TTY())
    reporter.render(run(), [{"status": "skipped"}])
    reporter.close()
    assert instances[0].updated and instances[0].stopped
    monkeypatch.setenv("CI", "true")
    stream = TTY()
    reporter = Reporter(stream=stream, interactive=True)
    reporter.emit({"event": "started"})
    assert json.loads(stream.getvalue())["event"] == "started"
    assert len(instances) == 1


@pytest.mark.parametrize("error", [None, "http_503", "http_502", "http_504", "task_timeout",
                                   "malformed_response", "response_too_large", "https_downgrade",
                                   "network_outage", "interrupted", "task_error", "unsupported_scheme"])
def test_runner_error_codes_remain_visible_and_success_has_no_error(error):
    stream = io.StringIO()
    Reporter(stream=stream).emit({"event": "task_finished", "error": error})
    result = json.loads(stream.getvalue())
    if error is None:
        assert "error" not in result
    else:
        assert result["error"] == error
