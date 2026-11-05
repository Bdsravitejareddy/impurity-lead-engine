"""Measure how leads convert, by priority, from the shared sales pipeline.

Scores are only useful if HOT leads convert better than REVIEW ones. This
report reads every stage change recorded by the dashboard and reports, per
priority, how many leads were contacted and how many of those replied or
progressed further. It writes nothing; the daily run logs it.
"""
from __future__ import annotations

import re
from collections import defaultdict

STAGE_ORDER = ["NEW", "REVIEWED", "OUTREACH READY", "CONTACTED", "REPLIED", "MEETING", "RFQ", "WON"]
CONTACTED = STAGE_ORDER.index("CONTACTED")
RESPONDED = STAGE_ORDER.index("REPLIED")
PAGE_SIZE = 1000


def pipeline_key(company: str | None, molecule: str | None) -> str:
    """Same key as web/src/data/pipelineStore.ts."""
    norm = lambda value: re.sub(r"\s+", " ", str(value or "").strip().lower())
    return f"{norm(company)}|{norm(molecule)}"


def _paged(builder) -> list[dict]:
    rows, start = [], 0
    while True:
        page = list(getattr(builder().range(start, start + PAGE_SIZE - 1).execute(), "data", None) or [])
        rows.extend(page)
        if len(page) < PAGE_SIZE:
            return rows
        start += PAGE_SIZE


def summarize_outcomes(opportunities: list[dict], events: list[dict]) -> dict:
    priority_by_key = {}
    for row in opportunities:
        company = (row.get("companies") or {})
        name = company.get("legal_name") or company.get("normalized_name")
        priority_by_key[pipeline_key(name, (row.get("molecules") or {}).get("canonical_name"))] = row.get("priority") or "UNQUALIFIED"
    furthest: dict[str, int] = {}
    lost: set[str] = set()
    for event in events:
        key, stage = event.get("pipeline_key"), event.get("to_stage")
        if stage == "LOST":
            lost.add(key)
        elif stage in STAGE_ORDER:
            furthest[key] = max(furthest.get(key, 0), STAGE_ORDER.index(stage))
    by_priority: dict[str, dict] = defaultdict(lambda: {"tracked": 0, "contacted": 0, "responded": 0, "won": 0, "lost": 0})
    for key in set(furthest) | lost:
        bucket = by_priority[priority_by_key.get(key, "UNKNOWN")]
        bucket["tracked"] += 1
        reached = furthest.get(key, 0)
        bucket["contacted"] += reached >= CONTACTED
        bucket["responded"] += reached >= RESPONDED
        bucket["won"] += reached == STAGE_ORDER.index("WON")
        bucket["lost"] += key in lost
    for bucket in by_priority.values():
        bucket["response_rate"] = round(bucket["responded"] / bucket["contacted"], 3) if bucket["contacted"] else None
    return {"tracked_leads": sum(bucket["tracked"] for bucket in by_priority.values()), "by_priority": dict(by_priority)}


def pipeline_outcome_report(client) -> dict:
    opportunities = _paged(lambda: client.table("opportunities").select("priority,companies(legal_name,normalized_name),molecules(canonical_name)").order("id"))
    events = _paged(lambda: client.table("opportunity_pipeline_events").select("pipeline_key,to_stage").order("changed_at"))
    return {"status": "COMPLETED", "processed": len(events), **summarize_outcomes(opportunities, events)}
