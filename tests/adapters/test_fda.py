import json
from pathlib import Path

from impurity_leads.adapters.fda import FDAAdapter


def test_fda_parser_emits_applicant_and_active_ingredient():
    payload = json.loads(Path("tests/fixtures/fda_record.json").read_text())
    records = FDAAdapter().parse(payload)
    assert records[0].company_name_raw == "Example Pharma"
    assert records[0].active_ingredient_raw == "Drug X"
