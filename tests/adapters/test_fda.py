import json
from pathlib import Path

from impurity_leads.adapters.fda import FDAAdapter


def test_fda_parser_emits_applicant_and_active_ingredient():
    payload = json.loads(Path("tests/fixtures/fda_record.json").read_text())
    records = FDAAdapter().parse(payload)
    assert records[0].company_name_raw == "Example Pharma"
    assert records[0].active_ingredient_raw == "Drug X"


def _application(number="ANDA012345", statuses=("Prescription",), dates=("20250101", "20260915")):
    return {
        "application_number": number, "sponsor_name": "Example Pharma",
        "openfda": {"substance_name": ["DRUG X"]},
        "products": [{"marketing_status": status, "active_ingredients": [{"name": "DRUG X HYDROCHLORIDE"}]} for status in statuses],
        "submissions": [{"submission_status_date": value} for value in dates],
    }


def test_fda_record_is_dated_by_its_latest_submission():
    record = FDAAdapter().parse(_application())[0]
    assert record.published_at.date().isoformat() == "2026-09-15"


def test_fda_skips_biologics_and_fully_discontinued_applications():
    assert FDAAdapter().parse(_application(number="BLA125057")) == []
    assert FDAAdapter().parse(_application(statuses=("Discontinued", "Discontinued"))) == []
    assert len(FDAAdapter().parse(_application(statuses=("Discontinued", "Prescription")))) == 1


def test_fda_prefers_the_harmonised_substance_name():
    assert [record.molecule_name_raw for record in FDAAdapter().parse(_application())] == ["DRUG X"]
