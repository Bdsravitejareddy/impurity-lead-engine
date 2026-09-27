from datetime import datetime, timedelta, timezone

from impurity_leads.models import Signal
from impurity_leads.score import score_signals, urgency_bonus


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


def test_historical_positive_signal_retains_technical_weight():
    assert score_signals([make_signal(35, 3650)]) == 35


def test_urgency_bonus_is_applied_once_from_newest_event():
    assert urgency_bonus(datetime.now(timezone.utc) - timedelta(days=30)) == 15
    assert urgency_bonus(datetime.now(timezone.utc) - timedelta(days=200)) == 8
    assert urgency_bonus(datetime.now(timezone.utc) - timedelta(days=500)) == 3
    assert urgency_bonus(datetime.now(timezone.utc) - timedelta(days=800)) == 0
    assert urgency_bonus(None) == 0


def test_score_uses_single_newest_event_urgency_bonus():
    now = datetime.now(timezone.utc)
    signals = [make_signal(35, 500), make_signal(18, 30)]
    assert score_signals(signals, now=now) == 68


def test_vendor_exclusion_zeroes_score():
    assert score_signals([make_signal(70)], is_vendor=True) == 0


def test_unknown_date_has_no_urgency_bonus():
    signal = make_signal(35)
    signal.event_date = None
    assert score_signals([signal], now=datetime.now(timezone.utc)) == 35


def test_duplicate_source_family_does_not_add_diversity():
    signals = [make_signal(35), make_signal(18)]
    signals[1].source_type = "job"
    assert score_signals(signals, now=datetime.now(timezone.utc)) == 68


def test_threshold_boundaries_remain_review_high_hot():
    now = datetime.now(timezone.utc)
    assert score_signals([make_signal(50, 800)], now=now) == 50
    assert score_signals([make_signal(65, 800)], now=now) == 65
    assert score_signals([make_signal(80, 800)], now=now) == 80
