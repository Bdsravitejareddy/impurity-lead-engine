"""Backend-authoritative contact quality scoring and portfolio gates."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from statistics import median
from typing import Any, Iterable


@dataclass(frozen=True)
class QualityConfig:
    daily_contact_target: int = 10
    min_contact_quality: float = 70
    min_identity_confidence: float = 70
    min_technical_relevance: float = 55
    min_median_quality: float = 72
    min_identity_coverage: float = 0.80
    min_technical_coverage: float = 0.70
    max_duplicate_rate: float = 0.15
    deep_research_opportunity_threshold: float = 85


def _bounded(value: Any, default: float = 0.0) -> float:
    try:
        return max(0.0, min(100.0, float(value)))
    except (TypeError, ValueError):
        return default


def _as_percent(value: Any, default: float | None = None) -> float | None:
    """Normalize stored decimal confidence values to the 0–100 score scale."""
    if value is None:
        return default
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if 0 < abs(number) <= 1:
        number *= 100
    return max(0.0, min(100.0, number))


# Rows back-filled from legacy contact_evidence carry the crawl's observation
# date as source_date, so their date says nothing about when the role held.
_UNDATED_SOURCE_KINDS = {"LEGACY_CONTACT_EVIDENCE"}


def _source_date(row: dict[str, Any]) -> date | None:
    if str(row.get("source_kind") or "").upper() in _UNDATED_SOURCE_KINDS:
        return None
    value = row.get("source_date") or row.get("published_at")
    if not value:
        return None
    try:
        return value if isinstance(value, date) and not isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _age_score(age_days: int) -> float:
    """How likely a role seen on a source this old is still current."""
    if age_days <= 365:
        return 85.0
    if age_days <= 730:
        return 65.0
    if age_days <= 1460:
        return 45.0
    return 25.0


def score_contact(contact: dict[str, Any], *, sources: Iterable[dict[str, Any]] = (), opportunities: Iterable[dict[str, Any]] = (), today: date | None = None) -> dict[str, Any]:
    """Score prioritisation quality, never purchase probability.

    ``basis`` records how each dimension was obtained: MEASURED (stored
    value), SOURCE_DATED (from the newest dated source), TITLE_KEYWORD, or
    ASSUMED (a placeholder default that must not be shown as a measurement).
    """
    today = today or datetime.now(timezone.utc).date()
    basis: dict[str, str] = {}
    source_rows = list(sources)
    if source_rows:
        source_rows = [row for row in source_rows if not row.get("status") or str(row.get("status")).upper() == "USED"]
    else:
        source_rows = [{"source_class": value} for value in (contact.get("source_classes") or [])]
    opportunity_rows = list(opportunities) or [{} for _ in range(int(contact.get("opportunity_count") or 0))]
    identity_value = contact.get("contact_confidence", contact.get("identity_confidence"))
    identity = _as_percent(identity_value)
    basis["identity"] = "MEASURED"
    if identity is None:
        identity = 80.0 if contact.get("profile_url") else 45.0
        basis["identity"] = "ASSUMED"
    # last_verified_at is stamped by batch runs, so it says nothing about
    # whether the title is still current; the newest dated source does.
    source_dates = [d for d in (_source_date(row) for row in source_rows) if d]
    newest_age = (today - max(source_dates)).days if source_dates else None
    current_role = _as_percent(contact.get("current_role_confidence"))
    basis["current_role"] = "MEASURED"
    if current_role is None:
        # A dated source naming the person's department at the company (a
        # paper affiliation) dates the role even when no job title is known.
        if (contact.get("title") or contact.get("department")) and newest_age is not None:
            current_role, basis["current_role"] = _age_score(newest_age), "SOURCE_DATED"
        else:
            current_role, basis["current_role"] = (40.0 if contact.get("title") else 20.0), "ASSUMED"
    reasons: dict[str, list[str]] = {}
    technical_value = _as_percent(contact.get("technical_relevance"))
    technical = technical_value or 0.0
    basis["technical_relevance"] = "MEASURED"
    if technical_value is not None and technical_value > 0:
        reasons["technical_relevance"] = ["person-direct technical evidence"]
    if not technical:
        basis["technical_relevance"] = "TITLE_KEYWORD"
        text = " ".join(str(contact.get(key) or "").casefold() for key in ("title", "department", "function"))
        technical = 75.0 if any(term in text for term in ("analytical", "quality", "impurity", "cmc", "stability", "regulatory", "api")) else 25.0
        reasons["technical_relevance"] = ["title/department keyword fallback"] if technical > 25 else ["no technical evidence"]
    classes = {str(row.get("source_class") or row.get("source_type") or "").upper() for row in source_rows}
    source_independence = min(100.0, len(classes) * 25.0) if classes else 0.0
    recency_value = _as_percent(contact.get("recency_score"))
    recency, basis["recency"] = (recency_value, "MEASURED") if recency_value is not None else ((_age_score(newest_age), "SOURCE_DATED") if newest_age is not None else (20.0, "ASSUMED"))
    status = str(contact.get("contactability") or contact.get("email_status") or contact.get("phone_status") or "UNKNOWN").upper()
    contactability = {"VERIFIED_PUBLIC": 100, "PATTERN_CONFIRMED": 85, "PROFESSIONAL": 70, "ROLE_ONLY": 45, "STALE": 10, "UNKNOWN": 20}.get(status, 20)
    opportunity_fit_value = _as_percent(contact.get("opportunity_fit"))
    opportunity_fit = opportunity_fit_value if opportunity_fit_value is not None else (80.0 if opportunity_rows else 25.0)
    basis["opportunity_fit"] = "MEASURED" if opportunity_fit_value is not None else "ASSUMED"
    dimensions = {
        "identity": identity,
        "current_role": current_role,
        "technical_relevance": technical,
        "source_independence": source_independence,
        "recency": recency,
        "contactability": float(contactability),
        "opportunity_fit": opportunity_fit,
    }
    weights = {"identity": .20, "current_role": .15, "technical_relevance": .25, "source_independence": .15, "recency": .10, "contactability": .10, "opportunity_fit": .05}
    score = round(sum(dimensions[key] * weights[key] for key in weights), 1)
    if identity < 70:
        reasons["identity"] = ["name present but independent corroboration is missing"]
    elif contact.get("identity_reason"):
        reasons["identity"] = [str(contact["identity_reason"])]
    if basis["current_role"] == "ASSUMED":
        reasons["current_role"] = ["current role not established by a dated source"]
    elif current_role < 70:
        reasons["current_role"] = ["current role evidence is stale"]
    if not source_rows:
        reasons["source_independence"] = ["no independent source classes"]
    return {"score": score, "dimensions": dimensions, "basis": basis, "identity_confidence": identity, "technical_relevance": technical, "diagnostics": reasons}


def portfolio_quality(contacts: Iterable[dict[str, Any]], *, duplicate_count: int = 0, config: QualityConfig = QualityConfig()) -> dict[str, Any]:
    rows = list(contacts)
    scored = [score_contact(row) for row in rows]
    scores = [item["score"] for item in scored]
    qualified = [item for item in scored if item["score"] >= config.min_contact_quality and item["identity_confidence"] >= config.min_identity_confidence and item["technical_relevance"] >= config.min_technical_relevance]
    identity_coverage = sum(item["identity_confidence"] >= config.min_identity_confidence for item in scored) / len(scored) if scored else 0.0
    technical_coverage = sum(item["technical_relevance"] >= config.min_technical_relevance for item in scored) / len(scored) if scored else 0.0
    duplicate_rate = duplicate_count / len(rows) if rows else 0.0
    metrics = {
        "raw_contacts_discovered": len(rows), "canonical_contacts": len(rows), "qualified_contacts": len(qualified),
        "average_quality": round(sum(scores) / len(scores), 1) if scores else 0.0,
        "median_quality": float(median(scores)) if scores else 0.0,
        "identity_coverage": round(identity_coverage, 3), "technical_coverage": round(technical_coverage, 3),
        "duplicate_rate": round(duplicate_rate, 3), "scores": scores,
    }
    metrics["gate_passed"] = bool(
        metrics["qualified_contacts"] >= config.daily_contact_target
        and metrics["median_quality"] >= config.min_median_quality
        and identity_coverage >= config.min_identity_coverage
        and technical_coverage >= config.min_technical_coverage
        and duplicate_rate <= config.max_duplicate_rate
    )
    metrics["ai_mode"] = "VALIDATION_ONLY" if metrics["gate_passed"] else "TARGETED_SEARCH"
    metrics["reason_for_ai_escalation"] = None if metrics["gate_passed"] else "portfolio quality gate not satisfied"
    return metrics
