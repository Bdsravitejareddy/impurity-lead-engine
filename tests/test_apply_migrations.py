import importlib.util
from pathlib import Path

import pytest


def _load():
    pytest.importorskip("psycopg")
    spec = importlib.util.spec_from_file_location("apply_migrations", Path("scripts/apply_migrations.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_first_use_records_hand_applied_migrations_and_runs_only_newer_ones():
    module = _load()
    files = ["20260906093111_resumable_crawler.sql", module.BASELINE, "20261105100000_company_domain_discovery.sql"]
    assert module.pending(files, set(), first_use=True) == (files[:2], files[2:])


def test_later_runs_apply_only_unrecorded_files():
    module = _load()
    files = ["a.sql", "b.sql", "c.sql"]
    assert module.pending(files, {"a.sql", "b.sql"}, first_use=False) == ([], ["c.sql"])
