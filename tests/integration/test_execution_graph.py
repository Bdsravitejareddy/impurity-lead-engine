"""Actual daily graph and production RPC mappings against disposable PostgreSQL."""
import json
from pathlib import Path
import threading

import httpx
import psycopg
from psycopg import sql
from psycopg.types.json import Jsonb
import pytest

from impurity_leads.config import Settings
from impurity_leads.execution.daily import execute_run
from impurity_leads.execution.retry import DatabaseUnavailable
from impurity_leads.seeds import CompanySeed
from impurity_leads.storage.task_store import SupabaseTaskStore


class PostgresTaskStore(SupabaseTaskStore):
    """Test transport only: real service-role SQL with production RPC arguments."""
    def __init__(self, uri, settings, stop_after_publish=None):
        super().__init__(None, settings)
        self.uri = uri
        self.stop_after_publish = stop_after_publish
        self.database_errors = []

    def _rpc(self, name, **params):
        query = sql.SQL("select public.{}({})").format(
            sql.Identifier(name), sql.SQL(",").join(
                sql.SQL("{} => %s").format(sql.Identifier(key)) for key in params
            ))
        values = [Jsonb(value) if isinstance(value, (dict, list)) else value for value in params.values()]
        try:
            with psycopg.connect(self.uri, autocommit=True) as conn:
                conn.execute("set role service_role")
                result = conn.execute(query, values).fetchone()[0]
            if name == "crawl_publish" and self.stop_after_publish is not None:
                self.stop_after_publish.set()
            return result
        except psycopg.Error as error:
            self.database_errors.append(error)
            raise DatabaseUnavailable("execution_store_unavailable") from error

    def tasks(self, summary=False):
        with psycopg.connect(self.uri, autocommit=True) as conn:
            conn.execute("set role service_role")
            return [row[0] for row in conn.execute(
                "select to_jsonb(t) from public.crawl_tasks t where run_id=%s order by task_key",
                (self.run["id"],))]


def fixture_client(ctx):
    def handler(request):
        host, path = request.url.host, request.url.path
        if host == "clinicaltrials.gov":
            return httpx.Response(403)
        if host == "api.fda.gov":
            return httpx.Response(200, json={"results": [json.loads(Path("tests/fixtures/fda_record.json").read_text())]})
        if path == "/robots.txt":
            return httpx.Response(404)
        if path == "/sitemap.xml":
            return httpx.Response(200, text=f"<urlset><url><loc>https://{host}/jobs/1</loc></url><url><loc>https://{host}/leadership</loc></url></urlset>")
        if path == "/jobs/1":
            return httpx.Response(200, text=Path("tests/fixtures/company_job.html").read_text())
        if path == "/leadership":
            return httpx.Response(200, text=Path("tests/fixtures/contact_leadership.html").read_text())
        return httpx.Response(404)
    return httpx.Client(transport=httpx.MockTransport(handler))


@pytest.mark.parametrize("workers", [1, 6])
def test_real_daily_graph_publication_resume_and_fresh_idempotency(db, pg_uri, tmp_path, workers):
    settings = Settings(per_domain_delay_seconds=0, scheduler_poll_seconds=.001)
    seeds = [CompanySeed("Example Pharma", "example.com", ["Drug X"])]
    stop = threading.Event()
    store = PostgresTaskStore(pg_uri, settings, stop_after_publish=stop)
    original = store.begin("graph-fixture", "first", False, {})
    assert execute_run(store, settings, seeds, tmp_path, workers=workers,
                       client_factory=fixture_client, stop=stop) == 130, store.database_errors
    assert not store.database_errors
    before = store.tasks()
    assert store.run["status"] == "paused"
    for table in ("companies", "molecules", "signals", "opportunities", "contacts", "contact_evidence", "opportunity_contacts"):
        assert db.execute(sql.SQL("select count(*) from {}").format(sql.Identifier(table))).fetchone()[0] > 0
    counts = {table: db.execute(sql.SQL("select count(*) from {}").format(sql.Identifier(table))).fetchone()[0]
              for table in ("companies", "molecules", "signals", "opportunities", "contacts", "contact_evidence", "opportunity_contacts")}

    resumed_store = PostgresTaskStore(pg_uri, settings)
    resumed = resumed_store.begin("graph-fixture", "second", False, {})
    assert resumed["id"] == original["id"] and resumed["resumed"]
    def forbid_network(ctx):
        raise AssertionError("completed network task repeated after publication")
    assert execute_run(resumed_store, settings, seeds, tmp_path, workers=workers,
                       client_factory=forbid_network) == 0, resumed_store.database_errors
    after = resumed_store.tasks()
    assert all(row["status"] in {"completed", "skipped"} for row in after)
    assert resumed_store.run["status"] == "completed"
    assert next(row for row in after if row["identifier"] == "clinical_trials")["status"] == "skipped"
    completed_before = {row["id"]: row["attempt_count"] for row in before if row["status"] in {"completed", "skipped"}}
    assert all(row["attempt_count"] == completed_before[row["id"]] for row in after if row["id"] in completed_before)
    assert (tmp_path / f"opportunities-{original['id']}.csv").exists()
    assert (tmp_path / f"opportunities-{original['id']}.xlsx").exists()

    fresh_store = PostgresTaskStore(pg_uri, settings)
    assert fresh_store.begin("graph-fixture", "third", True, {})["id"] != original["id"]
    assert execute_run(fresh_store, settings, seeds, tmp_path, workers=workers,
                       client_factory=fixture_client) == 0, fresh_store.database_errors
    for table, count in counts.items():
        assert db.execute(sql.SQL("select count(*) from {}").format(sql.Identifier(table))).fetchone()[0] == count
