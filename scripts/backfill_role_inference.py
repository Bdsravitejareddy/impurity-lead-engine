#!/usr/bin/env python3
"""Fill missing Contact 360 role hypotheses without fabricating observations."""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from uuid import NAMESPACE_URL, uuid5

from impurity_leads.role_inference import ROLE_ONTOLOGY_VERSION, infer_role_intelligence


def _client():
    from supabase import create_client

    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SECRET_KEY") or os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        raise RuntimeError("supabase_credentials_missing")
    return create_client(url, key)


def _rows(client, table: str, columns: str = "*") -> list[dict]:
    try:
        return list(getattr(client.table(table).select(columns).execute(), "data", None) or [])
    except Exception:
        return []


def run(mode: str = "apply", limit: int | None = None) -> dict:
    client = _client()
    contacts = [row for row in _rows(client, "contacts", "id,display_name,title,department,company_id,merged_into_contact_id") if not row.get("merged_into_contact_id")]
    if limit is not None:
        contacts = contacts[:limit]
    existing = _rows(client, "contact_jtbd", "id,contact_id,statement,basis,provenance")
    existing_by_contact: dict[str, set[str]] = {}
    for row in existing:
        existing_by_contact.setdefault(str(row.get("contact_id")), set()).add(str(row.get("statement") or ""))
    report = {"mode": mode, "ontology": ROLE_ONTOLOGY_VERSION, "contacts_seen": len(contacts), "eligible": 0, "updated": 0, "jtbd_added": 0, "themes_added": 0, "problems_added": 0, "unknown_roles": 0, "generated_at": datetime.now(timezone.utc).isoformat(), "profiles": []}
    for contact in contacts:
        inferred = infer_role_intelligence(contact, existing_by_contact.get(str(contact["id"]), set()))
        if not inferred["family"]:
            report["unknown_roles"] += 1
            continue
        report["eligible"] += 1
        profile = {"contact_id": contact["id"], "name": contact.get("display_name"), "family": inferred["family"], "level": inferred["level"], "confidence": inferred["confidence"], "jtbd_added": len(inferred["jtbd"]), "themes_added": 0, "problems_added": 0}
        if mode == "apply":
            for row in inferred["jtbd"]:
                client.table("contact_jtbd").upsert({"contact_id": contact["id"], **row}, on_conflict="id").execute()
                report["jtbd_added"] += 1
            for theme in inferred["themes"]:
                row = {"contact_id": contact["id"], "theme": theme, "evidence_count": 1, "confidence": inferred["confidence"], "source_ids": []}
                client.table("contact_themes").upsert(row, on_conflict="contact_id,theme").execute()
                report["themes_added"] += 1
                profile["themes_added"] += 1
            for problem in inferred["problems"]:
                problem_id = str(uuid5(NAMESPACE_URL, f"svak:role-problem:{contact['id']}:{problem}"))
                row = {"id": problem_id, "contact_id": contact["id"], "problem": problem, "context": "Role-based hypothesis; independently verify with person-specific evidence.", "attribution": "FUNCTIONAL", "technical_relevance": inferred["family"], "svak_relevance": "INFERRED", "confidence": inferred["confidence"], "source_ids": []}
                client.table("contact_problems").upsert(row, on_conflict="id").execute()
                report["problems_added"] += 1
                profile["problems_added"] += 1
            report["updated"] += 1
        report["profiles"].append(profile)
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("audit", "apply"), default="audit")
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    print(json.dumps(run(args.mode, args.limit), default=str, sort_keys=True))


if __name__ == "__main__":
    main()
