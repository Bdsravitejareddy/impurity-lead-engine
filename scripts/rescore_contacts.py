#!/usr/bin/env python3
"""Recompute every canonical contact's quality_diagnostics.

Stored scores were written by older scoring code that filled current role and
recency with fixed defaults. Default mode is read-only and reports how the
scores would change; ``--mode apply`` writes the recomputed diagnostics. No
contact identity field is modified.
"""

from __future__ import annotations

import argparse
import json
import os
from collections import Counter, defaultdict

from impurity_leads.contact_quality import score_contact

PAGE_SIZE = 1000


def _client():
    from supabase import create_client

    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SECRET_KEY") or os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        raise RuntimeError("supabase_credentials_missing")
    return create_client(url, key)


def _rows(client, table: str, columns: str = "*") -> list[dict]:
    # PostgREST caps each response, so page until a short page arrives.
    rows: list[dict] = []
    start = 0
    while True:
        page = list(getattr(client.table(table).select(columns).range(start, start + PAGE_SIZE - 1).execute(), "data", None) or [])
        rows.extend(page)
        if len(page) < PAGE_SIZE:
            return rows
        start += PAGE_SIZE


def rescore(contacts: list[dict], sources: list[dict], links: list[dict]) -> list[dict]:
    sources_by_contact: dict[str, list[dict]] = defaultdict(list)
    for row in sources:
        sources_by_contact[str(row.get("contact_id"))].append(row)
    links_by_contact: dict[str, list[dict]] = defaultdict(list)
    for row in links:
        links_by_contact[str(row.get("contact_id"))].append({"id": row.get("opportunity_id")})
    changes = []
    for contact in contacts:
        if contact.get("merged_into_contact_id"):
            continue
        contact_id = str(contact.get("id"))
        scored = score_contact(contact, sources=sources_by_contact.get(contact_id, []), opportunities=links_by_contact.get(contact_id, []))
        before = contact.get("quality_diagnostics") or {}
        changes.append({
            "id": contact_id,
            "display_name": contact.get("display_name"),
            "before": {"score": before.get("score"), "current_role": (before.get("dimensions") or {}).get("current_role")},
            "after": {"score": scored["score"], "current_role": scored["dimensions"]["current_role"], "basis": scored["basis"]["current_role"]},
            "diagnostics": {"score": scored["score"], "dimensions": scored["dimensions"], "basis": scored["basis"], "diagnostics": scored["diagnostics"]},
        })
    return changes


def summarize(changes: list[dict]) -> dict:
    return {
        "contacts": len(changes),
        "current_role_basis": dict(Counter(item["after"]["basis"] for item in changes)),
        "current_role_values_before": dict(Counter(str(item["before"]["current_role"]) for item in changes)),
        "current_role_values_after": dict(Counter(str(item["after"]["current_role"]) for item in changes)),
        "changes": [{key: item[key] for key in ("id", "display_name", "before", "after")} for item in changes],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("audit", "apply"), default="audit")
    args = parser.parse_args()
    client = _client()
    changes = rescore(
        _rows(client, "contacts"),
        [row for row in _rows(client, "contact_sources", "contact_id,source_type,status,source_date,source_kind") if str(row.get("status") or "").upper() == "USED"],
        _rows(client, "opportunity_contacts", "opportunity_id,contact_id"),
    )
    result = {"mode": args.mode, "summary": summarize(changes)}
    if args.mode == "apply":
        written = 0
        for item in changes:
            client.table("contacts").update({"quality_diagnostics": item["diagnostics"]}).eq("id", item["id"]).execute()
            written += 1
        result["written"] = written
    print(json.dumps(result, default=str, sort_keys=True))


if __name__ == "__main__":
    main()
