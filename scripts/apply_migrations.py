#!/usr/bin/env python3
"""Apply supabase/migrations/*.sql that have not run yet, in filename order.

Applied files are recorded in public.schema_migrations_applied. Every
migration up to BASELINE was applied by hand before this table existed, so
on first use those are recorded without running them again. Each file runs
in its own transaction; a failure stops the run and leaves later files alone.
"""
import os
import sys
from pathlib import Path

import psycopg

BASELINE = "20261104130000_company_normalization.sql"
MIGRATIONS = Path(__file__).resolve().parent.parent / "supabase" / "migrations"


def pending(files: list[str], applied: set[str], first_use: bool) -> tuple[list[str], list[str]]:
    """Return (files to record as already applied, files to run)."""
    if first_use:
        baseline = [name for name in files if name <= BASELINE]
        return baseline, [name for name in files if name > BASELINE]
    return [], [name for name in files if name not in applied]


def main() -> int:
    files = sorted(path.name for path in MIGRATIONS.glob("*.sql"))
    with psycopg.connect(os.environ["SUPABASE_DB_URL"], autocommit=True) as conn:
        first_use = conn.execute("select to_regclass('public.schema_migrations_applied') is null").fetchone()[0]
        conn.execute("create table if not exists public.schema_migrations_applied (filename text primary key, applied_at timestamptz not null default now())")
        conn.execute("alter table public.schema_migrations_applied enable row level security")
        conn.execute("revoke all on table public.schema_migrations_applied from anon, authenticated")
        applied = {row[0] for row in conn.execute("select filename from public.schema_migrations_applied")}
        baseline, to_run = pending(files, applied, first_use)
        for name in baseline:
            conn.execute("insert into public.schema_migrations_applied (filename) values (%s) on conflict do nothing", (name,))
        for name in to_run:
            with conn.transaction():
                conn.execute((MIGRATIONS / name).read_text())
                conn.execute("insert into public.schema_migrations_applied (filename) values (%s)", (name,))
            print(f"applied {name}")
        print(f"recorded {len(baseline)} baseline migrations; applied {len(to_run)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
