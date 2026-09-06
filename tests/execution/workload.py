"""Deterministic offline workload shared by equivalence tests and benchmark."""
import copy
import json
import threading
import time
from collections import Counter
from contextlib import ExitStack, contextmanager
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import httpx

from impurity_leads.config import Settings
from impurity_leads.execution.daily import execute_run
from impurity_leads.execution.http import CrawlClient, HostGate
from impurity_leads.seeds import CompanySeed
from .support import MemoryTasks


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


class FixedDatetime(datetime):
    @classmethod
    def now(cls, tz=None):
        value = cls(2026, 9, 5, 12, tzinfo=timezone.utc)
        return value.astimezone(tz) if tz else value.replace(tzinfo=None)


@contextmanager
def fixed_clock():
    with ExitStack() as stack:
        for module in ("adapters.clinical_trials", "adapters.fda", "adapters.company_site",
                       "execution.crawl", "contacts.pipeline"):
            stack.enter_context(patch(f"impurity_leads.{module}.datetime", FixedDatetime))
        yield


class WorkloadStore(MemoryTasks):
    def __init__(self, interrupt=False):
        super().__init__()
        self.published = []
        self.stop = threading.Event()
        self.interrupt = interrupt
        self.interrupted = False

    def publish(self, task, rows, checkpoint):
        with self.lock:
            self.published.extend(copy.deepcopy(rows))
            current = next(row for row in self.rows if row["id"] == task["id"])
            current["checkpoint_json"] = copy.deepcopy(checkpoint)

    def save(self, task, status, checkpoint, result, **kwargs):
        value = super().save(task, status, checkpoint, result, **kwargs)
        if (self.interrupt and not self.interrupted and task["stage"] == "company_crawling"
                and status == "running" and checkpoint.get("index", 0) >= 1):
            self.interrupted = True
            self.stop.set()
        return value


class Workload:
    def __init__(self, domains=12, latency=.01, retry=True, interrupt=False):
        self.seeds = [CompanySeed("Example Pharma" if i == 0 else f"Fixture Pharma {i:02}",
                                  "example.com" if i == 0 else f"fixture{i:02}.example", ["Drug X"])
                      for i in range(domains)]
        self.settings = Settings(per_domain_delay_seconds=0, scheduler_poll_seconds=.001,
                                 retry_base_seconds=0, shutdown_drain_seconds=1)
        self.store = WorkloadStore(interrupt)
        self.gate = HostGate(0)
        self.latency = latency
        self.retry = retry
        self.requests = Counter()
        self.clients = []
        self.lock = threading.Lock()
        self.fixtures = {name: (FIXTURES / name).read_text() for name in
                         ("clinical_trials_study.json", "fda_record.json", "company_job.html", "contact_leadership.html")}

    def payload(self, filename, seed):
        return self.fixtures[filename].replace("Example Pharma", seed.company_name).replace("example.com", seed.domain)

    def handler(self, request):
        host, path = request.url.host, request.url.path
        with self.lock:
            self.requests[(host, path)] += 1
            count = self.requests[(host, path)]
        time.sleep(self.latency)
        if host == "clinicaltrials.gov":
            return httpx.Response(200, json={"studies": [json.loads(self.payload("clinical_trials_study.json", s)) for s in self.seeds]})
        if host == "api.fda.gov":
            return httpx.Response(200, json={"results": [json.loads(self.payload("fda_record.json", s)) for s in self.seeds]})
        if host == "index.commoncrawl.org":
            if path == "/collinfo.json":
                return httpx.Response(200, json=[{"id": "fixture-index"}])
            return httpx.Response(200, text="")
        seed = next(s for s in self.seeds if s.domain == host)
        if path == "/robots.txt":
            return httpx.Response(404)
        if path == "/sitemap.xml":
            return httpx.Response(200, text=f"<urlset><url><loc>https://{host}/jobs/1</loc></url><url><loc>https://{host}/leadership</loc></url></urlset>")
        if path == "/jobs/1":
            if self.retry and count == 1:
                return httpx.Response(503)
            return httpx.Response(200, text=self.payload("company_job.html", seed))
        if path == "/leadership":
            return httpx.Response(200, text=self.payload("contact_leadership.html", seed))
        return httpx.Response(404)

    def client_factory(self, ctx):
        raw = httpx.Client(transport=httpx.MockTransport(self.handler), trust_env=False)
        with self.lock:
            self.clients.append(raw)
        return CrawlClient(ctx, self.settings, self.gate, client=raw)

    def execute(self, directory, workers):
        return execute_run(self.store, self.settings, self.seeds, directory, workers=workers,
                           client_factory=self.client_factory, stop=self.store.stop)

    def outputs(self):
        rows = self.store.tasks()
        processing = next(row["result_json"] for row in rows if row["stage"] == "processing_scoring")
        contacts = [item for row in rows if row["stage"] == "contact_enrichment"
                    for item in row["result_json"].get("contacts", [])]
        return {"signals": processing["signals"], "opportunities": processing["opportunities"], "contacts": contacts}

    def counts(self):
        rows = self.store.tasks()
        return {"tasks": len(rows), "attempts": sum(r["attempt_count"] for r in rows),
                "retries": sum(max(0, r["attempt_count"] - 1) for r in rows),
                "requests": sum(self.requests.values())}

    def close(self):
        for client in self.clients:
            client.close()
