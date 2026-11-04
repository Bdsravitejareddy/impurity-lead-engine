"""Rescore stored opportunities that a run did not re-qualify.

An opportunity row is only written when its pair qualifies, so a pair that
stops qualifying, or was scored under older rules, kept its old score. This
rebuilds each such pair from every persisted signal with the current rules.
A pair that no longer qualifies keeps priority REVIEW (the column requires
one) with its real score below 50, which drops it from qualified views.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from impurity_leads.aggregate import aggregate_candidates
from impurity_leads.models import Signal

_RANK = {"HOT": 3, "HIGH": 2, "REVIEW": 1}
_QUALIFIED_SCORE = 50
_PAGE = 1000


def _paged(query_factory) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    while True:
        batch = query_factory().range(len(rows), len(rows) + _PAGE - 1).execute().data or []
        rows.extend(batch)
        if len(batch) < _PAGE:
            return rows


def _stale_opportunities(client, qualified_before: datetime | None) -> list[dict[str, Any]]:
    def query():
        q = client.table("opportunities").select("id,company_id,molecule_id,score,priority,rationale,likely_need_type,decision_maker_role,last_qualified_at")
        return q.lt("last_qualified_at", qualified_before.isoformat()) if qualified_before else q
    return _paged(query)


def rescore_stale_opportunities(client, *, qualified_before: datetime | None, now: datetime | None = None, apply: bool = True) -> dict[str, Any]:
    """Rescore opportunities last qualified before ``qualified_before`` (all when None)."""
    now = now or datetime.now(timezone.utc)
    by_company: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in _stale_opportunities(client, qualified_before):
        by_company[str(row["company_id"])].append(row)
    metrics = {"evaluated": 0, "rescored": 0, "unchanged": 0, "demoted": 0, "lapsed": 0, "without_signals": 0, "changes": []}
    for company_id, opportunities in by_company.items():
        signal_rows = _paged(lambda: client.table("signals").select("*").eq("company_id", company_id))
        # A company that sells impurities is excluded from every pair, as in the pipeline.
        is_vendor = any(row.get("signal_type") == "impurity_vendor_exclusion" for row in signal_rows)
        by_molecule: dict[str, list[Signal]] = defaultdict(list)
        for row in signal_rows:
            if row.get("molecule_id") and row.get("signal_type") != "impurity_vendor_exclusion":
                by_molecule[str(row["molecule_id"])].append(
                    Signal.model_validate({**row, "company_name": company_id, "molecule_name": str(row["molecule_id"])}))
        for opportunity in opportunities:
            metrics["evaluated"] += 1
            signals = by_molecule.get(str(opportunity["molecule_id"]))
            if not signals:
                metrics["without_signals"] += 1
                continue
            candidate = aggregate_candidates(signals, now=now)[0]
            score = 0 if is_vendor else candidate["score"]
            priority = None if is_vendor else candidate["priority"]
            update = {
                "score": score,
                "priority": priority or "REVIEW",
                "rationale": candidate["rationale"],
                "likely_need_type": candidate["likely_need_type"],
                "decision_maker_role": candidate["decision_maker_role"],
            }
            if all(opportunity.get(key) == value for key, value in update.items()):
                metrics["unchanged"] += 1
                continue
            metrics["rescored"] += 1
            was_qualified = int(opportunity.get("score") or 0) >= _QUALIFIED_SCORE
            if was_qualified and score < _QUALIFIED_SCORE:
                metrics["lapsed"] += 1
            elif score >= _QUALIFIED_SCORE and _RANK.get(update["priority"], 0) < _RANK.get(str(opportunity.get("priority")), 0):
                metrics["demoted"] += 1
            metrics["changes"].append({"opportunity_id": opportunity["id"], "before_score": opportunity.get("score"),
                                       "before_priority": opportunity.get("priority"), "after_score": score,
                                       "after_priority": update["priority"]})
            if apply:
                client.table("opportunities").update(update).eq("id", opportunity["id"]).execute()
    return metrics


def run_stale_opportunity_rescore(settings, *, qualified_before: datetime | None, apply: bool = True) -> dict[str, Any]:
    """Post-crawl stage and CLI entry point; ``qualified_before=None`` rescores every row."""
    if not (getattr(settings, "supabase_url", None) and getattr(settings, "supabase_secret_key", None)):
        return {"status": "SKIPPED", "reason": "supabase_credentials_missing"}
    from supabase import create_client

    client = create_client(settings.supabase_url, settings.supabase_secret_key)
    result = rescore_stale_opportunities(client, qualified_before=qualified_before, apply=apply)
    return {**result, "status": "COMPLETED", "processed": result["evaluated"], "applied": apply}
