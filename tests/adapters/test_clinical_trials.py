import json
from pathlib import Path

from impurity_leads.adapters.clinical_trials import ClinicalTrialsAdapter


def test_trial_parser_emits_company_and_molecule():
    payload = json.loads(Path("tests/fixtures/clinical_trials_study.json").read_text())
    records = ClinicalTrialsAdapter().parse(payload)
    assert records[0].company_name_raw == "Example Pharma"
    assert records[0].molecule_name_raw == "EX-101"
    assert records[0].metadata_json["phase"] == "PHASE3"


def test_trial_parser_skips_placebo_and_vehicle_arms():
    payload = {"protocolSection": {
        "identificationModule": {"nctId": "NCT00000001", "briefTitle": "Example study"},
        "sponsorCollaboratorsModule": {"leadSponsor": {"name": "Example Pharma"}},
        "armsInterventionsModule": {"interventions": [
            {"type": "DRUG", "name": "EX-101"},
            {"type": "DRUG", "name": "Placebo"},
            {"type": "DRUG", "name": "Vehicle Cream"},
        ]},
    }}
    records = ClinicalTrialsAdapter().parse(payload)
    assert [record.molecule_name_raw for record in records] == ["EX-101"]
