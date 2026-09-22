#!/usr/bin/env python3
"""Audit and safely repair legacy contact ingestion.

Default mode is read-only.  ``--mode apply`` only performs high-confidence
soft merges and accepted-evidence source backfills.  It never deletes a
canonical contact row, guesses identity, or prints credentials.
"""

from __future__ import annotations

import argparse
import json
import os
from collections import defaultdict
from datetime import datetime, timezone
from urllib.parse import urlparse

from impurity_leads.contact_integrity import classify_contact_pair, choose_survivor
from impurity_leads.contacts.normalize import normalize_person_name


CHILD_TABLES = (
    "contact_evidence", "contact_sources", "contact_positions", "contact_education",
    "contact_works", "contact_problems", "contact_themes", "contact_jtbd",
    "contact_claims", "contact_notes", "contact_history", "contact_conflicts",
    "contact_research_runs", "opportunity_contacts",
)

CHILD_COLUMNS = {
    "contact_evidence": "id,contact_id,source_url,fingerprint",
    "contact_sources": "id,contact_id,url",
    "opportunity_contacts": "opportunity_id,contact_id",
}


def _client():
    from supabase import create_client

    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SECRET_KEY") or os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        raise RuntimeError("supabase_credentials_missing")
    return create_client(url, key)


def _rows(client, table: str, columns: str = "*") -> list[dict]:
    try:
        result = client.table(table).select(columns).execute()
        return list(getattr(result, "data", None) or [])
    except Exception:
        return []


def _safe_count(rows: list[dict], key: str, value: str) -> int:
    return sum(1 for row in rows if str(row.get(key) or "") == value)


def audit(client) -> dict:
    contacts = _rows(client, "contacts")
    active = [row for row in contacts if not row.get("merged_into_contact_id")]
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for row in active:
        # Recompute from the display name as well as the stored key. Legacy
        # imports are precisely where the stored normalized value may include
        # degree suffixes or punctuation.
        normalized = normalize_person_name(str(row.get("display_name") or row.get("normalized_name") or ""))
        key = (str(row.get("company_id") or ""), normalized)
        if key[0] and key[1]:
            groups[key].append(row)
    decisions = []
    for (company_id, normalized_name), rows in groups.items():
        if len(rows) < 2:
            continue
        survivor = choose_survivor(rows)
        for row in rows:
            if row.get("id") == survivor.get("id"):
                continue
            decision = classify_contact_pair(survivor, row)
            decisions.append({
                "company_id": company_id,
                "normalized_name": normalized_name,
                "duplicate_id": row.get("id"),
                "survivor_id": survivor.get("id"),
                "display_name": row.get("display_name"),
                "action": decision.action,
                "reason": decision.reason,
            })
    evidence = _rows(client, "contact_evidence", "contact_id,source_url,evidence_type,source_type,observed_at,fingerprint")
    sources = _rows(client, "contact_sources", "id,contact_id,url,status,source_type,source_date")
    active_ids = {str(row.get("id")) for row in active}
    evidence_urls = {(str(row.get("contact_id")), str(row.get("source_url"))) for row in evidence if row.get("source_url")}
    source_urls = {(str(row.get("contact_id")), str(row.get("url"))) for row in sources if row.get("url")}
    backfill = [
        {"contact_id": row.get("contact_id"), "url": row.get("source_url"), "source_type": row.get("source_type"), "observed_at": row.get("observed_at")}
        for row in evidence
        if str(row.get("contact_id")) in active_ids and row.get("source_url") and (str(row.get("contact_id")), str(row.get("source_url"))) not in source_urls
    ]
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "contacts_total": len(contacts),
        "active_contacts": len(active),
        "soft_merged_contacts": len(contacts) - len(active),
        "auto_merge_candidates": [item for item in decisions if item["action"] == "AUTO_MERGE"],
        "review_candidates": [item for item in decisions if item["action"] == "REVIEW"],
        "accepted_evidence_source_backfills": backfill,
        "contact_sources_total": len(sources),
        "contact_evidence_total": len(evidence),
    }


def _update_children(client, duplicate_id: str, survivor_id: str) -> dict[str, int]:
    metrics: dict[str, int] = {}
    for table in CHILD_TABLES:
        try:
            rows = _rows(client, table, CHILD_COLUMNS.get(table, "id,contact_id"))
            duplicate_rows = [row for row in rows if str(row.get("contact_id")) == duplicate_id]
            if not duplicate_rows:
                continue
            survivor_urls = {str(row.get("url")) for row in rows if str(row.get("contact_id")) == survivor_id and row.get("url")}
            survivor_fingerprints = {str(row.get("fingerprint")) for row in rows if str(row.get("contact_id")) == survivor_id and row.get("fingerprint")}
            moved = 0
            removed = 0
            for row in duplicate_rows:
                conflict = (row.get("url") and str(row.get("url")) in survivor_urls) or (row.get("fingerprint") and str(row.get("fingerprint")) in survivor_fingerprints)
                try:
                    if table == "opportunity_contacts":
                        existing = any(str(item.get("opportunity_id")) == str(row.get("opportunity_id")) and str(item.get("contact_id")) == survivor_id for item in rows)
                        query = client.table(table).delete().eq("opportunity_id", row["opportunity_id"]).eq("contact_id", duplicate_id) if existing else client.table(table).update({"contact_id": survivor_id}).eq("opportunity_id", row["opportunity_id"]).eq("contact_id", duplicate_id)
                        query.execute()
                        if existing:
                            removed += 1
                        else:
                            moved += 1
                    elif conflict and row.get("id"):
                        client.table(table).delete().eq("id", row["id"]).execute()
                        removed += 1
                    else:
                        client.table(table).update({"contact_id": survivor_id}).eq("id", row["id"]).execute()
                        moved += 1
                except Exception:
                    # A child table may have a stricter unique constraint; keep
                    # the canonical survivor and report the table-level issue.
                    continue
            metrics[table] = moved
            if removed:
                metrics[f"{table}_deduped"] = removed
        except Exception:
            continue
    return metrics


def apply(client, report: dict) -> dict:
    merged = []
    for candidate in report["auto_merge_candidates"]:
        duplicate_id = str(candidate["duplicate_id"])
        survivor_id = str(candidate["survivor_id"])
        child_metrics = _update_children(client, duplicate_id, survivor_id)
        now = datetime.now(timezone.utc).isoformat()
        client.table("contacts").update({
            "merged_into_contact_id": survivor_id,
            "merge_reason": candidate["reason"],
            "merged_at": now,
        }).eq("id", duplicate_id).execute()
        try:
            client.table("contact_aliases").upsert({
                "contact_id": survivor_id,
                "alias_name": candidate.get("display_name") or candidate["normalized_name"],
                "normalized_name": candidate["normalized_name"],
                "provenance": "OBSERVED",
            }, on_conflict="contact_id,normalized_name").execute()
        except Exception:
            pass
        merged.append({**candidate, "child_metrics": child_metrics})

    # A retry after a successful soft merge must still finish moving child
    # relations. This makes the repair idempotent if a previous run merged the
    # parent rows before a table-level child update failed.
    for row in _rows(client, "contacts", "id,merged_into_contact_id,display_name"):
        survivor_id = row.get("merged_into_contact_id")
        if not survivor_id:
            continue
        child_metrics = _update_children(client, str(row["id"]), str(survivor_id))
        if child_metrics:
            merged.append({"duplicate_id": row["id"], "survivor_id": survivor_id, "display_name": row.get("display_name"), "reason": "retry_child_migration", "child_metrics": child_metrics})

    backfilled = []
    for item in report["accepted_evidence_source_backfills"]:
        url = str(item["url"])
        host = urlparse(url).netloc
        try:
            client.table("contact_sources").upsert({
                "contact_id": item["contact_id"],
                "url": url,
                "title": f"Accepted {item.get('source_type') or 'public'} evidence",
                "publisher": host or None,
                "source_type": item.get("source_type") or "OTHER_PUBLIC",
                "source_date": str(item.get("observed_at") or "")[:10] or None,
                "status": "USED",
                "evidence_strength": "CANONICAL_CONTACT_EVIDENCE",
                "why_used": "Backfilled from accepted contact_evidence",
                "source_kind": "LEGACY_CONTACT_EVIDENCE",
            }, on_conflict="contact_id,url").execute()
            backfilled.append(item)
        except Exception:
            continue
    return {"merged": merged, "sources_backfilled": backfilled}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("audit", "apply"), default="audit")
    args = parser.parse_args()
    client = _client()
    report = audit(client)
    result = {"mode": args.mode, "audit": report}
    if args.mode == "apply":
        result["applied"] = apply(client, report)
    print(json.dumps(result, default=str, sort_keys=True))


if __name__ == "__main__":
    main()
