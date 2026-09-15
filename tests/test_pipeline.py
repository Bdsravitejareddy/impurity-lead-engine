from datetime import datetime, timezone

from impurity_leads.models import SourceRecord
from impurity_leads.pipeline import process_records, process_records_with_candidates
from impurity_leads.storage.memory import MemoryLeadStore


def test_pipeline_creates_opportunity_from_multiple_signals():
    now = datetime.now(timezone.utc)
    records = [
        SourceRecord(
            source_name="trial",
            source_type="trial",
            source_url="https://a",
            fetched_at=now,
            company_name_raw="Example Pharma",
            molecule_name_raw="Drug X",
            signal_text="Phase III small molecule program",
            metadata_json={"phase": "PHASE3"},
        ),
        SourceRecord(
            source_name="site",
            source_type="job",
            source_url="https://b",
            fetched_at=now,
            company_name_raw="Example Pharma",
            molecule_name_raw="Drug X",
            signal_text="impurity characterization and forced degradation for Drug X",
        ),
    ]
    store = MemoryLeadStore()
    opportunities = process_records(records, store)
    assert opportunities
    assert store.signals
    assert store.opportunities
    assert opportunities[0].priority == "HIGH"


def test_pipeline_never_qualifies_known_impurity_vendor():
    now = datetime.now(timezone.utc)
    records = [
        SourceRecord(
            source_name="site",
            source_type="site",
            source_url="https://vendor.example/services",
            fetched_at=now,
            company_name_raw="Vendor Labs",
            molecule_name_raw="Drug X",
            signal_text="We manufacture and supply custom impurity reference standards worldwide.",
            metadata_json={"is_impurity_vendor": True},
        )
    ]
    store = MemoryLeadStore()
    assert process_records(records, store) == []


def test_pipeline_returns_resolved_unqualified_candidate_for_persistence():
    now = datetime.now(timezone.utc)
    records = [SourceRecord(source_name="regulatory", source_type="regulatory", source_url="https://reg.example/y",
                             fetched_at=now, published_at=now, company_name_raw="New Pharma", molecule_name_raw="Drug Y",
                             signal_text="Regulatory application", metadata_json={"application_number": "ANDA-1"})]
    opportunities, candidates = process_records_with_candidates(records, MemoryLeadStore())
    assert opportunities == []
    assert candidates and candidates[0]["priority"] is None
