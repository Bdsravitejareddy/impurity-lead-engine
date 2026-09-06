from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import psycopg
import pytest
from psycopg.types.json import Jsonb


def rpc(db, name, *args):
    args = tuple(Jsonb(v) if isinstance(v, (dict, list)) else v for v in args)
    return db.execute(f"select public.{name}({','.join(['%s'] * len(args))})", args).fetchone()[0]


def begin(db, fingerprint="v1", fresh=False):
    return rpc(db, "crawl_begin", fingerprint, "coordinator", fresh, {}, 120)


def plan(db, run, count=1):
    rpc(db, "crawl_plan", run["id"], run["coordinator_token"], [
        dict(task_key=f"task-{i}", task_type="source", stage="sources", identifier=str(i), domain=None, checkpoint_json={})
        for i in range(count)
    ])


def claim(db, run):
    return rpc(db, "crawl_claim", run["id"], run["coordinator_token"], "sources", "worker", 120)


def save(db, run, task, status="completed", checkpoint=None, result=None):
    return rpc(db, "crawl_save", task["id"], task["lease_token"], run["coordinator_token"], status,
               checkpoint or {}, result or {}, None, 0, 1.0)


def test_coordinator_and_claims_are_atomic(db, pg_uri):
    def acquire(_):
        with psycopg.connect(pg_uri, autocommit=True) as c:
            try:
                return begin(c)
            except psycopg.Error:
                return None
    with ThreadPoolExecutor(2) as pool:
        runs = list(pool.map(acquire, range(2)))
    assert sum(r is not None for r in runs) == 1
    run = next(r for r in runs if r)
    plan(db, run, 2)
    def take(_):
        with psycopg.connect(pg_uri, autocommit=True) as c:
            return claim(c, run)
    with ThreadPoolExecutor(2) as pool:
        tasks = list(pool.map(take, range(2)))
    assert len({t["id"] for t in tasks}) == 2


def test_expiry_fencing_attempt_limit_and_terminal_immutability(db):
    run = begin(db)
    plan(db, run)
    for attempt in range(1, 4):
        task = claim(db, run)
        assert task["attempt_count"] == attempt
        db.execute("update crawl_tasks set lease_expires_at=now()-interval '1 second'")
        with pytest.raises(psycopg.Error):
            save(db, run, task)
    assert claim(db, run) is None
    assert db.execute("select status from crawl_tasks").fetchone()[0] == "permanent_failed"


def test_resume_fresh_incompatible_and_age_limit(db):
    run = begin(db)
    with pytest.raises(psycopg.Error):
        begin(db, fresh=True)
    db.execute("update crawl_runs set coordinator_expires_at=now()-interval '1 second'")
    resumed = begin(db)
    assert resumed["id"] == run["id"] and resumed["resumed"]
    db.execute("update crawl_runs set coordinator_expires_at=now()-interval '1 second', started_at=now()-interval '49 hours'")
    newer = begin(db)
    assert newer["id"] != run["id"]
    assert db.execute("select status from crawl_runs where id=%s", (run["id"],)).fetchone()[0] == "abandoned"
    db.execute("update crawl_runs set coordinator_expires_at=now()-interval '1 second'")
    assert begin(db, "v2")["id"] != newer["id"]


def test_payload_limits_and_security(db):
    run = begin(db)
    plan(db, run)
    task = claim(db, run)
    for checkpoint, result in [({"cursor": "x" * 16384}, {}), ({}, {"records": "x" * (4 * 1024 * 1024)})]:
        with pytest.raises(psycopg.Error):
            save(db, run, task, checkpoint=checkpoint, result=result)
    for role in ("anon", "authenticated"):
        db.execute(f"set role {role}")
        with pytest.raises(psycopg.Error):
            begin(db)
        with pytest.raises(psycopg.Error):
            db.execute("select * from crawl_tasks")
        db.execute("reset role")
    db.execute("set role service_role")
    saved = save(db, run, task, result={"version": 1, "records": []})
    assert saved["status"] == "completed"
    with pytest.raises(psycopg.Error):
        save(db, run, task)
    db.execute("reset role")


def test_publication_idempotent_and_atomic(db):
    run = begin(db)
    plan(db, run)
    task = claim(db, run)
    row = {"table": "companies", "on_conflict": "id", "row": {"id": str(uuid4()), "normalized_name": "example"}}
    def publish(rows, checkpoint):
        return rpc(db, "crawl_publish", task["id"], task["lease_token"], run["coordinator_token"], rows, checkpoint)
    publish([row], {"cursor": 1})
    publish([row], {"cursor": 1})
    assert db.execute("select count(*) from companies").fetchone()[0] == 1
    invalid = {"table": "companies", "on_conflict": "id", "row": {"id": str(uuid4()), "normalized_name": "rollback"}}
    with pytest.raises(psycopg.Error):
        publish([invalid, {"table": "crawl_runs", "row": {}}], {"cursor": 2})
    assert db.execute("select count(*) from companies").fetchone()[0] == 1
    assert db.execute("select checkpoint_json from crawl_tasks").fetchone()[0] == {"cursor": 1}


def test_release_domain_exclusion_metrics_and_stale_coordinator(db):
    run = begin(db)
    plan(db, run, 2)
    db.execute("update crawl_tasks set domain='example.test'")
    task = claim(db, run)
    assert claim(db, run) is None
    released = save(db, run, task, status="pending", checkpoint={"cursor": 1})
    assert released["attempt_count"] == 1 and released["lease_token"] is None
    task = claim(db, run)
    assert task["checkpoint_json"] == {"cursor": 1}
    assert rpc(db, "crawl_renew", task["id"], task["lease_token"], run["coordinator_token"], 120)
    assert rpc(db, "crawl_heartbeat", run["id"], run["coordinator_token"], 120)["id"] == run["id"]
    rpc(db, "crawl_domain_result", "example.test", False, "connect_error", 60, task["id"], task["lease_token"], run["coordinator_token"])
    assert db.execute("select error_count from crawl_domains").fetchone()[0] == 1
    save(db, run, task)
    assert claim(db, run) is None
    assert not rpc(db, "crawl_renew", task["id"], task["lease_token"], run["coordinator_token"], 120)
    done = rpc(db, "crawl_finish_run", run["id"], run["coordinator_token"], "completed_with_errors", "export",
               {"records": 2, "signals": 3, "failure_count": 1, "active_elapsed_seconds": 4})
    assert (done["records_seen"], done["records_inserted"], done["errors"], float(done["duration_seconds"])) == (2, 3, 1, 4)
    with pytest.raises(psycopg.Error):
        rpc(db, "crawl_heartbeat", run["id"], run["coordinator_token"], 120)


def test_publication_preserves_review_and_observation_times(db):
    run = begin(db)
    plan(db, run)
    task = claim(db, run)
    company, molecule, opportunity = (str(uuid4()) for _ in range(3))
    rows = [
        {"table": "companies", "on_conflict": "id", "row": {"id": company, "normalized_name": "preserved"}},
        {"table": "molecules", "on_conflict": "id", "row": {"id": molecule, "canonical_name": "drug"}},
        {"table": "opportunities", "on_conflict": "company_id,molecule_id", "row": {"id": opportunity, "company_id": company, "molecule_id": molecule, "score": 70, "priority": "HIGH", "rationale": "evidence"}},
    ]
    def publish(rows):
        rpc(db, "crawl_publish", task["id"], task["lease_token"], run["coordinator_token"], rows, {})
    publish(rows)
    db.execute("update opportunities set status='dismissed',dismissal_reason='reviewed',first_qualified_at='2020-01-01'")
    publish(rows)
    assert db.execute("select status,dismissal_reason,extract(year from first_qualified_at) from opportunities").fetchone() == ('dismissed','reviewed',2020)
    malicious = dict(rows[2], row=dict(rows[2]["row"], status="new"))
    with pytest.raises(psycopg.Error):
        publish([malicious])
    db.execute("update crawl_runs set coordinator_expires_at=now()-interval '1 second'")
    renewed = begin(db)
    with pytest.raises(psycopg.Error):
        publish(rows)
    with pytest.raises(psycopg.Error):
        save(db, run, task)
    assert renewed["id"] == run["id"]


def test_retry_delay_exhausted_release_and_progress_are_durable(db):
    run = begin(db)
    plan(db, run)
    task = claim(db, run)
    progress = save(db, run, task, status="running", checkpoint={"page": 2}, result={"version": 1, "records": [{"name": "parsed"}]})
    assert progress["lease_token"] == task["lease_token"]
    delayed = rpc(db, "crawl_save", task["id"], task["lease_token"], run["coordinator_token"], "retryable_failed",
                  progress["checkpoint_json"], progress["result_json"], "http_429", 60, 2.0)
    assert delayed["result_json"] == progress["result_json"]
    assert claim(db, run) is None
    db.execute("update crawl_tasks set next_eligible_at=now()-interval '1 second'")
    task = claim(db, run)
    with pytest.raises(psycopg.Error):
        rpc(db, "crawl_renew", task["id"], progress["lease_token"], run["coordinator_token"], 120)
    save(db, run, task, status="pending")
    task = claim(db, run)
    assert task["attempt_count"] == 3
    assert save(db, run, task, status="pending")["status"] == "permanent_failed"
    assert claim(db, run) is None


def test_execution_credentials_private_existing_summary_policy_preserved(db):
    run = begin(db)
    db.execute("set role authenticated")
    assert db.execute("select id,status,records_seen from crawl_runs").fetchone()[1] == "running"
    with pytest.raises(psycopg.Error):
        db.execute("select coordinator_token from crawl_runs")
    db.execute("reset role")
    assert db.execute("select count(*) from pg_proc p join pg_namespace n on n.oid=p.pronamespace where n.nspname='public' and p.proname like 'crawl_%' and p.prosecdef").fetchone()[0] == 0
    db.execute("set role service_role")
    assert db.execute("select coordinator_token from crawl_runs").fetchone()[0]
    db.execute("reset role")


@pytest.mark.parametrize('released_status', ['pending', 'retryable_failed'])
def test_heartbeat_race_after_release_is_not_database_outage(db, released_status):
    run = begin(db)
    plan(db, run)
    task = claim(db, run)
    save(db, run, task, status=released_status)
    assert rpc(db, 'crawl_renew', task['id'], task['lease_token'], run['coordinator_token'], 120) is False


def test_shared_common_crawl_cooldown_blocks_network_stages_only(db):
    run = begin(db)
    rpc(db, 'crawl_plan', run['id'], run['coordinator_token'], [
        dict(task_key=stage, task_type='crawl', stage=stage, identifier=stage,
             domain='example.test' if stage != 'structured_sources' else None, checkpoint_json={})
        for stage in ('company_crawling', 'contact_enrichment', 'structured_sources')
    ])
    db.execute("insert into crawl_domains(domain,next_crawl_at) values('index.commoncrawl.org',now()+interval '1 minute')")
    for stage in ('company_crawling', 'contact_enrichment'):
        assert rpc(db, 'crawl_claim', run['id'], run['coordinator_token'], stage, 'worker', 120) is None
    assert rpc(db, 'crawl_claim', run['id'], run['coordinator_token'], 'structured_sources', 'worker', 120)
    db.execute("update crawl_domains set next_crawl_at=now()-interval '1 second'")
    assert rpc(db, 'crawl_claim', run['id'], run['coordinator_token'], 'company_crawling', 'worker', 120)
