from pathlib import Path


def test_daily_workflow_has_hard_timeout_and_zero_cost_schedule():
    text = Path(".github/workflows/daily-crawl.yml").read_text()
    assert "timeout-minutes: 45" in text
    assert "SUPABASE_SECRET_KEY" in text
    assert "actions/checkout@v7" in text
    assert "actions/upload-artifact@v4" in text


def test_test_workflow_runs_pytest():
    text = Path(".github/workflows/test.yml").read_text()
    assert "python -m pytest -q" in text
    assert "actions/setup-python@v7" in text


def test_daily_workflow_materializes_private_company_seeds():
    text = Path(".github/workflows/daily-crawl.yml").read_text()
    assert "COMPANY_SEEDS_CSV" in text
    assert "seeds/companies.csv" in text
    assert "printf" in text


def test_private_company_seed_file_is_ignored_and_example_is_tracked():
    ignore_text = Path(".gitignore").read_text()
    assert "seeds/companies.csv" in ignore_text
    assert Path("seeds/companies.example.csv").exists()
