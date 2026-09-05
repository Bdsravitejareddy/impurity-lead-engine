import json
from pathlib import Path

from impurity_leads.adapters.clinical_trials import ClinicalTrialsAdapter


def test_trial_parser_emits_company_and_molecule():
    payload = json.loads(Path("tests/fixtures/clinical_trials_study.json").read_text())
    records = ClinicalTrialsAdapter().parse(payload)
    assert records[0].company_name_raw == "Example Pharma"
    assert records[0].molecule_name_raw == "EX-101"
    assert records[0].metadata_json["phase"] == "PHASE3"
