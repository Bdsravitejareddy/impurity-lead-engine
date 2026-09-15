from datetime import datetime, timedelta, timezone

from impurity_leads.aggregate import aggregate_candidates, aggregate_opportunities
from impurity_leads.models import Signal


def test_aggregate_requires_company_and_molecule_and_surfaces_high():
    now = datetime.now(timezone.utc)
    signals = [
        Signal(company_name="Example Pharma", molecule_name="Drug X", source_type="trial", signal_type="phase_iii", source_url="https://a", evidence_text="Phase III", discovered_at=now, base_weight=18, confidence=1.0, fingerprint="a"),
        Signal(company_name="Example Pharma", molecule_name="Drug X", source_type="job", signal_type="impurity_characterization", source_url="https://b", evidence_text="impurity characterization", discovered_at=now, base_weight=38, confidence=1.0, fingerprint="b"),
        Signal(company_name="Example Pharma", molecule_name="Drug X", source_type="site", signal_type="stability", source_url="https://c", evidence_text="forced degradation", discovered_at=now, base_weight=18, confidence=1.0, fingerprint="c"),
    ]
    opportunities = aggregate_opportunities(signals)
    assert len(opportunities) == 1
    assert opportunities[0].priority in {"HIGH", "HOT"}


def test_direct_rfq_remains_hot_even_below_numeric_threshold():
    now = datetime.now(timezone.utc)
    signals = [Signal(company_name="Example Pharma", molecule_name="Drug X", source_type="rfq",
                      signal_type="direct_impurity_rfq", source_url="https://rfq", evidence_text="RFQ",
                      discovered_at=now, base_weight=70, confidence=1.0, fingerprint="rfq")]
    opportunities = aggregate_opportunities(signals)
    assert opportunities[0].priority == "HOT"


def test_low_score_resolved_pair_is_retained_as_candidate_for_later_rescoring():
    now = datetime.now(timezone.utc)
    candidates = aggregate_candidates([
        Signal(company_name="New Pharma", molecule_name="Drug Y", source_type="regulatory",
               signal_type="regulatory_application", source_url="https://regulatory.example/y",
               evidence_text="Application", discovered_at=now, base_weight=22, confidence=1.0,
               fingerprint="candidate-y"),
    ])
    assert len(candidates) == 1
    assert candidates[0]["company_name"] == "New Pharma"
    assert candidates[0]["molecule_name"] == "Drug Y"
    assert candidates[0]["score"] < 50
    assert candidates[0]["priority"] is None


def test_existing_pair_is_rescored_and_promoted_when_new_evidence_arrives():
    now = datetime.now(timezone.utc)
    event_date = now - timedelta(days=400)
    day_one = Signal(company_name="Rescore Pharma", molecule_name="Drug Z", source_type="regulatory",
                     signal_type="regulatory_application", source_url="https://regulatory.example/z",
                     evidence_text="Application", event_date=event_date, discovered_at=now, base_weight=30, confidence=1.0,
                     fingerprint="rescore-1")
    day_two = Signal(company_name="Rescore Pharma", molecule_name="Drug Z", source_type="publication",
                     signal_type="impurity_characterization", source_url="https://journal.example/z",
                     evidence_text="Impurity characterization", event_date=event_date, discovered_at=now, base_weight=15, confidence=1.0,
                     fingerprint="rescore-2")
    first = aggregate_candidates([day_one])[0]
    second = aggregate_candidates([day_one, day_two])[0]
    assert first["score"] < 50
    assert second["score"] >= 50
    assert second["priority"] == "REVIEW"
    assert second["signal_fingerprints"] == ["rescore-1", "rescore-2"]
