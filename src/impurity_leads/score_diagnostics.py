"""Explain score_signals contributions without changing scoring semantics."""
from datetime import datetime, timezone
from .score import freshness_penalty, score_signals, urgency_bonus


def explain_score(signals, *, now: datetime | None = None, is_vendor: bool = False) -> dict:
    now = now or datetime.now(timezone.utc)
    rows=[]
    for signal in signals:
        age = (now - signal.event_date).days if signal.event_date else None
        freshness = freshness_penalty(signal.event_date, now)
        effective = signal.base_weight + freshness
        rows.append({
            "signal_type": signal.signal_type,
            "source_type": signal.source_type,
            "base_weight": signal.base_weight,
            "confidence": signal.confidence,
            "event_date": signal.event_date.isoformat() if signal.event_date else None,
            "age_days": age,
            "freshness_adjustment": freshness,
            "other_modifiers": 0,
            "effective_contribution": effective,
        })
    raw = sum(item["effective_contribution"] for item in rows)
    source_count = len({signal.source_type for signal in signals})
    diversity = 8 if source_count >= 3 else 4 if source_count == 2 else 0
    latest_event = max((signal.event_date for signal in signals if signal.event_date), default=None)
    urgency = urgency_bonus(latest_event, now)
    unclamped = raw + diversity + urgency
    clamped = score_signals(signals, is_vendor=is_vendor, now=now)
    types = {signal.signal_type for signal in signals}
    priority = "HOT" if clamped >= 80 or "direct_impurity_rfq" in types else "HIGH" if clamped >= 65 else "REVIEW" if clamped >= 50 else None
    return {"signals": rows, "raw_total": raw, "diversity_bonus": diversity, "newest_event": latest_event.isoformat() if latest_event else None, "urgency_bonus": urgency, "unclamped_total": unclamped, "clamped_total": clamped, "final_priority": priority, "priority": priority}
