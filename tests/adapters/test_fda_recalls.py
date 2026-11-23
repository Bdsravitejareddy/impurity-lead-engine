from datetime import date, datetime, timedelta, timezone

from impurity_leads.adapters.fda_recalls import FDARecallAdapter, molecule_from_description
from impurity_leads.adapters.queries import RECALL_PAGE_SIZE, recall_params
from impurity_leads.pipeline import process_records_with_candidates
from impurity_leads.storage.memory import MemoryLeadStore


def recall(**overrides):
    row = {
        "recall_number": "D-0166-2027",
        "recalling_firm": "Hikma Pharmaceuticals USA INC.",
        "reason_for_recall": "CGMP Deviations: N-nitroso-ciprofloxacin results above the FDA recommended interim control limit.",
        "product_description": "Ciprofloxacin Tablets, USP, 750 mg, 50-count bottle",
        "recall_initiation_date": (date.today() - timedelta(days=30)).strftime("%Y%m%d"),
        "classification": "Class II",
        "status": "Ongoing",
        "country": "United States",
        "openfda": {"substance_name": ["CIPROFLOXACIN HYDROCHLORIDE"], "application_number": ["ANDA076126"]},
    }
    row.update(overrides)
    return row


def test_impurity_recall_becomes_dated_record():
    [record] = FDARecallAdapter().parse(recall())
    assert record.company_name_raw == "Hikma Pharmaceuticals USA INC."
    assert record.molecule_name_raw == "CIPROFLOXACIN HYDROCHLORIDE"
    assert record.source_type == "recall"
    assert record.metadata_json["recall_number"] == "D-0166-2027"
    assert record.published_at.tzinfo is not None


def test_recall_for_other_reasons_is_ignored():
    assert FDARecallAdapter().parse(recall(reason_for_recall="Lack of sterility assurance")) == []


def test_molecule_falls_back_to_product_description():
    [record] = FDARecallAdapter().parse(recall(openfda={}, reason_for_recall="Failed Impurities/Degradation Specifications"))
    assert record.molecule_name_raw == "Ciprofloxacin"
    assert molecule_from_description("Formoterol Fumarate Inhalation Solution, 20mcg/2mL") == "Formoterol Fumarate"


def test_recall_params_cover_three_years_newest_first():
    params = recall_params(page=2, today=date(2026, 11, 23))
    assert "recall_initiation_date:[20231124 TO 20261123]" in params["search"]
    assert params["skip"] == 2 * RECALL_PAGE_SIZE
    assert params["sort"] == "recall_initiation_date:desc"


def test_recent_nitrosamine_recall_is_hot_and_plain_impurity_recall_is_high():
    adapter = FDARecallAdapter()
    records = adapter.parse(recall()) + adapter.parse(recall(
        recall_number="D-0073-2027", recalling_firm="The Ritedose Corporation",
        reason_for_recall="Failed Impurities/Degradation Specification",
        openfda={"substance_name": ["FORMOTEROL FUMARATE"]},
    ))
    opportunities, _ = process_records_with_candidates(records, MemoryLeadStore())
    priority = {o.company_name: o.priority for o in opportunities}
    assert priority["Hikma Pharmaceuticals USA INC."] == "HOT"
    assert priority["The Ritedose Corporation"] == "HIGH"


def test_repackager_and_distributor_recalls_are_skipped():
    adapter = FDARecallAdapter()
    for firm in ["RemedyRepack Inc.", "Direct Rx", "AvKARE", "Amerisource Health Services LLC",
                 "The Harvard Drug Group LLC dba Major Pharmaceuticals and Rugby Laboratories", "SKY PACKAGING"]:
        assert adapter.parse(recall(recalling_firm=firm)) == [], firm
    assert adapter.parse(recall(recalling_firm="Glenmark Pharmaceuticals Inc., USA"))
