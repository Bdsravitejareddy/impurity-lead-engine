from datetime import datetime, timezone

from impurity_leads.aggregate import aggregate_opportunities
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
