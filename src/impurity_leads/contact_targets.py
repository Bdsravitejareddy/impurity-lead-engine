"""Opportunities that should get contact search, not only those found in this run.

Contact search used to start from the opportunities that qualified in the
current crawl. A lead found on Monday never got contacts, because on Tuesday
its signals were already stored and no longer counted as new. Contact search
now covers every qualified opportunity in the database as well.
"""
from __future__ import annotations

from typing import Any, Iterable

from impurity_leads.models import Opportunity
from impurity_leads.seed_sources import QUALIFYING_SCORE, _paged

ALLOWED_PRIORITIES = {"HOT", "HIGH", "REVIEW"}


def database_contact_targets(client) -> list[Opportunity]:
    rows = _paged(lambda: client.table("opportunities")
                  .select("score,priority,status,companies(legal_name,normalized_name,merged_into_company_id),molecules(canonical_name)")
                  .gte("score", QUALIFYING_SCORE).order("score", desc=True).order("id"))
    targets: list[Opportunity] = []
    for row in rows:
        company = row.get("companies") or {}
        molecule = (row.get("molecules") or {}).get("canonical_name")
        name = company.get("legal_name") or company.get("normalized_name")
        priority = row.get("priority")
        if (str(row.get("status") or "").lower() == "dismissed" or company.get("merged_into_company_id")
                or not name or not molecule or priority not in ALLOWED_PRIORITIES):
            continue
        targets.append(Opportunity(company_name=name, molecule_name=molecule, score=int(row["score"]),
                                   priority=priority, rationale="existing qualified opportunity"))
    return targets


def merge_contact_targets(current: Iterable[Opportunity], stored: Iterable[Opportunity]) -> list[Opportunity]:
    """This run's opportunities first, then stored ones, one entry per company and molecule."""
    seen: set[tuple[str, str]] = set()
    merged: list[Opportunity] = []
    for opportunity in [*current, *stored]:
        key = (opportunity.company_name.casefold(), opportunity.molecule_name.casefold())
        if key in seen:
            continue
        seen.add(key)
        merged.append(opportunity)
    return merged


def load_contact_targets(settings) -> list[Opportunity]:
    if not (getattr(settings, "supabase_url", None) and getattr(settings, "supabase_secret_key", None)):
        return []
    from supabase import create_client
    try:
        return database_contact_targets(create_client(settings.supabase_url, settings.supabase_secret_key))
    except Exception:
        # A read failure must not stop the crawl; the run's own opportunities still get contacts.
        return []
