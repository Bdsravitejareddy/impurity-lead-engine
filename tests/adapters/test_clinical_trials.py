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


def _study(sponsor_class="INDUSTRY", status="RECRUITING", phases=("PHASE3",), interventions=(("DRUG", "EX-101"),), collaborators=()):
    return {"protocolSection": {
        "identificationModule": {"nctId": "NCT00000002", "briefTitle": "Example"},
        "statusModule": {"overallStatus": status},
        "sponsorCollaboratorsModule": {"leadSponsor": {"name": "Lead Org", "class": sponsor_class}, "collaborators": [{"name": n, "class": c} for n, c in collaborators]},
        "designModule": {"phases": list(phases)},
        "armsInterventionsModule": {"interventions": [{"type": t, "name": n} for t, n in interventions]},
    }}


def test_academic_sponsor_is_not_a_buyer_unless_industry_collaborates():
    assert ClinicalTrialsAdapter().parse(_study(sponsor_class="OTHER")) == []
    records = ClinicalTrialsAdapter().parse(_study(sponsor_class="OTHER", collaborators=[("Example Pharma", "INDUSTRY")]))
    assert records[0].company_name_raw == "Example Pharma"


def test_withdrawn_and_terminated_trials_are_skipped():
    assert ClinicalTrialsAdapter().parse(_study(status="WITHDRAWN")) == []
    assert ClinicalTrialsAdapter().parse(_study(status="TERMINATED")) == []


def test_phase_two_three_trial_uses_latest_phase_and_clean_names():
    records = ClinicalTrialsAdapter().parse(_study(phases=("PHASE2", "PHASE3"), interventions=(("DRUG", "Abrocitinib 100 mg"), ("DRUG", "Abrocitinib 200 mg"))))
    assert [record.molecule_name_raw for record in records] == ["Abrocitinib"]
    assert records[0].metadata_json["phase"] == "PHASE3"


def _with_other_names(*interventions):
    study = _study()
    study["protocolSection"]["armsInterventionsModule"]["interventions"] = [
        {"type": "DRUG", "name": name, "otherNames": list(other)} for name, other in interventions]
    return study


def test_obvious_biologics_entered_as_drug_are_dropped():
    study = _study(interventions=(("DRUG", "Pembrolizumab"), ("DRUG", "Aflibercept 2 mg"), ("DRUG", "Insulin glargine"),
                                  ("DRUG", "Semaglutide"), ("DRUG", "Trastuzumab deruxtecan"), ("DRUG", "Epoetin alfa"),
                                  ("DRUG", "Filgrastim"), ("DRUG", "Tisagenlecleucel"), ("DRUG", "Abrocitinib")))
    assert [record.molecule_name_raw for record in ClinicalTrialsAdapter().parse(study)] == ["Abrocitinib"]


def test_development_codes_map_to_their_nonproprietary_name():
    study = _with_other_names(("BAY 94-8862", ["Kerendia", "finerenone"]), ("AZD1234", ["Brandix"]), ("EX-101", []))
    records = ClinicalTrialsAdapter().parse(study)
    assert [record.molecule_name_raw for record in records] == ["finerenone", "Brandix", "EX-101"]
    assert records[0].metadata_json["development_code"] == "BAY 94-8862"
    assert "development_code" not in records[2].metadata_json


def test_development_code_for_a_biologic_is_dropped():
    study = _with_other_names(("MK-3475", ["pembrolizumab", "Keytruda"]), ("ABC-123", ["abcitinib"]))
    assert [record.molecule_name_raw for record in ClinicalTrialsAdapter().parse(study)] == ["abcitinib"]
