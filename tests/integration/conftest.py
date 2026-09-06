"""Disposable, socket-only PostgreSQL. Never reads application credentials."""
from pathlib import Path
import tempfile
import os
from urllib.parse import urlsplit, parse_qs

import pytest
psycopg = pytest.importorskip("psycopg", reason="PostgreSQL integration dependencies are optional")


@pytest.fixture(scope="session")
def pg_uri():
    explicit = os.environ.get("TEST_DATABASE_URL")
    if explicit:
        parsed = urlsplit(explicit)
        # This fixture drops public. Accept only the explicit dedicated local CI DB.
        if (parsed.scheme not in {"postgres", "postgresql"}
                or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}
                or parsed.path != "/impurity_test" or parse_qs(parsed.query)):
            pytest.fail("TEST_DATABASE_URL must target localhost/impurity_test without query overrides")
        yield explicit
        return
    pgembed = pytest.importorskip("pgembed", reason="Install pgembed or use dedicated local TEST_DATABASE_URL")
    import fasteners
    PostgresServer = pgembed.PostgresServer
    with tempfile.TemporaryDirectory(prefix="crawl-pg-", dir="/tmp") as root:
        root = Path(root)
        PostgresServer.runtime_path = root
        PostgresServer._lock = fasteners.InterProcessLock(root / "lock")
        server = PostgresServer(root / "data")
        try:
            yield server.get_uri()
        finally:
            server._cleanup()


@pytest.fixture
def db(pg_uri):
    with psycopg.connect(pg_uri, autocommit=True) as conn:
        conn.execute("drop schema public cascade; create schema public")
        for role in ("anon", "authenticated", "service_role"):
            if not conn.execute("select 1 from pg_roles where rolname=%s", (role,)).fetchone():
                conn.execute(f"create role {role}" + (" bypassrls" if role == "service_role" else ""))
        conn.execute("grant usage on schema public to anon, authenticated, service_role")
        schema = Path("supabase/schema.sql").read_text().split("-- Resumable crawler execution")[0]
        # pgembed omits pgcrypto; gen_random_uuid is built into PostgreSQL 13+.
        conn.execute(schema.replace("create extension if not exists pgcrypto;", ""))
        for migration in sorted(Path("supabase/migrations").glob("*_resumable_crawler.sql")):
            conn.execute(migration.read_text())
        yield conn
