from datetime import datetime, timezone

from impurity_leads.models import Signal


def freshness_penalty(event_date: datetime | None, now: datetime | None = None) -> int:
    """Compatibility helper: positive evidence is never penalized for age."""
    return 0


def urgency_bonus(event_date: datetime | None, now: datetime | None = None) -> int:
    if event_date is None:
        return 0
    now = now or datetime.now(timezone.utc)
    days = max(0, (now - event_date).days)
    if days <= 180:
        return 15
    if days <= 365:
        return 8
    if days <= 730:
        return 3
    return 0


def score_signals(signals: list[Signal], is_vendor: bool = False, now: datetime | None = None) -> int:
    if is_vendor or not signals:
        return 0
    raw = sum(s.base_weight for s in signals)
    independent_sources = len({s.source_type for s in signals})
    if independent_sources >= 3:
        raw += 8
    elif independent_sources == 2:
        raw += 4
    latest_event = max((s.event_date for s in signals if s.event_date), default=None)
    raw += urgency_bonus(latest_event, now)
    return max(0, min(100, raw))
