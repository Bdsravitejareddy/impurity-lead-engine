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


# Evidence that a company works on impurities for this molecule. Without one of
# these a pair can be REVIEW at most, however many context records it has.
IMPURITY_SIGNAL_TYPES = frozenset({
    "direct_impurity_rfq", "reference_standard", "nitrosamine_ndsri", "genotoxic_impurity",
    "impurity_characterization", "degradation_product", "stability",
})
# Development-stage and filing records show activity, not impurity demand.
CONTEXT_SIGNAL_TYPES = frozenset({"phase_ii", "phase_iii", "regulatory_application"})
CONTEXT_CAP = 35


def context_age_factor(event_date: datetime | None, now: datetime | None = None) -> float:
    """How much a phase or filing record still says about current activity.

    A 2015 filing is not the same signal as a 2026 one. Impurity evidence is
    not decayed: an impurity a company characterized stays relevant.
    """
    if event_date is None:
        # Unknown age is not evidence of old age; FDA and trial records are dated.
        return 1.0
    days = max(0, ((now or datetime.now(timezone.utc)) - event_date).days)
    if days <= 365:
        return 1.0
    if days <= 730:
        return 0.75
    if days <= 1460:
        return 0.5
    return 0.25


def _diminishing(weights: list[float]) -> float:
    """Strongest record counts in full, each further one of the type half as much."""
    return sum(weight / (2 ** index) for index, weight in enumerate(sorted(weights, reverse=True)))


def score_signals(signals: list[Signal], is_vendor: bool = False, now: datetime | None = None) -> int:
    if is_vendor or not signals:
        return 0
    # Summing every record let volume alone reach 100: five bare FDA filings
    # scored HOT. Repeats of a type now add diminishing weight and context
    # types share one cap.
    by_type: dict[str, list[float]] = {}
    for s in signals:
        weight = s.base_weight * context_age_factor(s.event_date, now) if s.signal_type in CONTEXT_SIGNAL_TYPES else s.base_weight
        by_type.setdefault(s.signal_type, []).append(weight)
    context = sum(_diminishing(weights) for kind, weights in by_type.items() if kind in CONTEXT_SIGNAL_TYPES)
    evidence = sum(_diminishing(weights) for kind, weights in by_type.items() if kind not in CONTEXT_SIGNAL_TYPES)
    raw = round(evidence + min(context, CONTEXT_CAP))
    independent_sources = len({s.source_type for s in signals})
    if independent_sources >= 3:
        raw += 8
    elif independent_sources == 2:
        raw += 4
    latest_event = max((s.event_date for s in signals if s.event_date), default=None)
    raw += urgency_bonus(latest_event, now)
    return max(0, min(100, raw))
