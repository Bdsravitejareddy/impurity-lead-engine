from datetime import datetime, timedelta, timezone

from impurity_leads.models import Signal
from impurity_leads.score import score_signals


def make_signal(weight: int, days_old: int = 0) -> Signal:
    now = datetime.now(timezone.utc)
    return Signal(
        company_name="Example Pharma",
        molecule_name="Drug X",
        source_type="job",
        signal_type="impurity_characterization",
        source_url=f"https://example.com/{weight}/{days_old}",
        evidence_text="impurity characterization",
        event_date=now - timedelta(days=days_old),
        discovered_at=now,
        base_weight=weight,
        confidence=1.0,
        fingerprint=f"{weight}-{days_old}",
    )


def test_scoring_applies_freshness_penalty():
    assert score_signals([make_signal(70, 400)]) == 40


def test_vendor_exclusion_zeroes_score():
    assert score_signals([make_signal(70)], is_vendor=True) == 0
