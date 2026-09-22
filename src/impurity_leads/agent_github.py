"""GitHub issue/comment transport for the ChatGPT Work bridge.

GitHub is treated as an untrusted message bus. This module only serialises
bounded job context and extracts marked JSON; it never executes comment text.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from datetime import datetime, timezone
from typing import Any
from impurity_leads.zero_cost import ProviderUsage

AGENT_JOB_START = "<!-- SVAK_AGENT_JOB_START -->"
AGENT_JOB_END = "<!-- SVAK_AGENT_JOB_END -->"
WORK_RESULT_START = "<!-- SVAK_WORK_RESULT_START -->"
WORK_RESULT_END = "<!-- SVAK_WORK_RESULT_END -->"
MAX_COMMENT_CHARS = 200_000


def build_issue_payload(job: dict[str, Any]) -> dict[str, Any]:
    known = job.get("known_entities") or {}
    job_kind = str(job.get("job_kind") or "CONTACT_RESEARCH")
    return {
        "agent_job_id": str(job.get("id") or ""),
        "job_kind": job_kind,
        "opportunity_id": str(job.get("opportunity_id")) if job.get("opportunity_id") else None,
        "molecule_id": str(job.get("molecule_id") or known.get("molecule_id") or ""),
        "company_id": str(job.get("company_id") or known.get("company_id") or ""),
        "candidate_id": str(job.get("candidate_id") or ""),
        "company": known.get("company") or job.get("company") or "UNKNOWN",
        "molecule": known.get("molecule") or job.get("molecule") or "UNKNOWN",
        "opportunity_score": known.get("opportunity_score", job.get("priority")),
        "quality_before": job.get("quality_before") or {},
        "missing_dimensions": job.get("missing_dimensions") or [],
        "known_contacts": job.get("known_contacts") or [],
        "known_entities": known,
        "known_claims": job.get("known_claims") or [],
        "known_sources": job.get("known_sources") or [],
        "research_goal": job.get("research_goal") or "Resolve only the missing dimensions.",
        "agent_prompt": job.get("agent_prompt") or "Use the bounded research instructions in this issue.",
        "research_limits": {
            "max_people": 15,
            "max_sources": 10,
            "public_sources_only": True,
            "no_authenticated_scraping": True,
        },
        "required_json_schema": "Use the schema in agent_prompt; return JSON only.",
    }


def render_issue_body(job: dict[str, Any]) -> str:
    payload = build_issue_payload(job)
    readable = (
        "SVAK automated Work research job. Research only the unresolved dimensions "
        "listed in the payload. Use bounded public-web research and return the "
        "required JSON as one issue comment between the result markers.\n\n"
        "Do not bypass authentication, CAPTCHA, paywalls, or private data. Do not "
        "guess emails. Do not modify code, merge PRs, or access Supabase.\n\n"
        "Bounded Work instructions and the strict output schema:\n"
        f"{payload.get('agent_prompt', '')}\n\n"
        f"{AGENT_JOB_START}\n{json.dumps(payload, indent=2, ensure_ascii=False)}\n{AGENT_JOB_END}\n\n"
        "Return only a JSON result comment using:\n"
        f"{WORK_RESULT_START}\n{{...}}\n{WORK_RESULT_END}"
    )
    return readable


def extract_marked_json(text: str, start_marker: str = WORK_RESULT_START, end_marker: str = WORK_RESULT_END) -> tuple[Any | None, str | None]:
    if not isinstance(text, str) or len(text) > MAX_COMMENT_CHARS:
        return None, "comment_too_large"
    start = text.find(start_marker)
    end = text.find(end_marker, start + len(start_marker)) if start >= 0 else -1
    if start < 0 or end < 0:
        return None, "markers_missing"
    raw = text[start + len(start_marker):end].strip()
    if not raw:
        return None, "empty_result"
    try:
        return json.loads(raw), None
    except json.JSONDecodeError:
        return None, "invalid_json"


def extract_job_payload(issue_body: str) -> tuple[dict[str, Any] | None, str | None]:
    value, error = extract_marked_json(issue_body, AGENT_JOB_START, AGENT_JOB_END)
    if error:
        return None, error
    if not isinstance(value, dict) or not value.get("agent_job_id"):
        return None, "invalid_job_payload"
    return value, None


def _run_gh(args: list[str], *, repo: str) -> str:
    env = os.environ.copy()
    env["GH_REPO"] = repo
    result = subprocess.run(["gh", *args], check=True, capture_output=True, text=True, env=env, timeout=30)
    return result.stdout.strip()


def select_ready_agent_jobs(rows: list[dict[str, Any]], *, limit: int = 5, contact_reserve: int = 2) -> list[dict[str, Any]]:
    """Select READY jobs fairly so molecule work cannot starve contacts."""
    if limit <= 0:
        return []
    ordered = sorted(rows, key=lambda row: int(row.get("priority") or 0), reverse=True)
    contacts = [row for row in ordered if str(row.get("job_kind") or "CONTACT_RESEARCH") == "CONTACT_RESEARCH"]
    molecules = [row for row in ordered if str(row.get("job_kind") or "CONTACT_RESEARCH") == "MOLECULE_INTELLIGENCE"]
    opportunities = [row for row in ordered if str(row.get("job_kind") or "CONTACT_RESEARCH") == "OPPORTUNITY_EVIDENCE"]
    reserved = contacts[:min(max(contact_reserve, 0), limit)]
    selected_ids = {str(row.get("id")) for row in reserved}
    if molecules and len(selected_ids) < limit:
        selected_ids.add(str(molecules[0].get("id")))
        reserved.append(molecules[0])
    # Candidate enrichment is deliberately bounded but must make progress in
    # the same cycle; reserve up to two slots when eligible opportunity jobs
    # exist so high-priority molecule work cannot starve them.
    for opportunity in opportunities[:min(2, max(0, limit - len(selected_ids)))]:
        selected_ids.add(str(opportunity.get("id")))
        reserved.append(opportunity)
    remainder = [row for row in ordered if str(row.get("id")) not in selected_ids]
    selected = []
    opportunity_count = 0
    for row in reserved + remainder:
        if len(selected) >= limit:
            break
        if str(row.get("job_kind") or "CONTACT_RESEARCH") == "OPPORTUNITY_EVIDENCE":
            if opportunity_count >= 2:
                continue
            opportunity_count += 1
        selected.append(row)
    return selected


def export_ready_agent_jobs(client: Any, *, repo: str, limit: int = 5, provider_usage: ProviderUsage | None = None) -> dict[str, Any]:
    """Export READY jobs once. GitHub failures remain observable and retryable."""
    def ready_query():
        # supabase-py request builders mutate their query parameters. Build a
        # fresh query for each kind so one filter cannot hide the others.
        return client.table("agent_research_jobs").select("*").eq("status", "READY").is_("github_issue_number", "null")
    # Fetch bounded slices per kind before applying fairness. A single global
    # priority-ordered LIMIT can hide every contact job behind high-priority
    # molecule jobs and make the reserve ineffective.
    contact_rows = ready_query().eq("job_kind", "CONTACT_RESEARCH").order("priority", desc=True).limit(limit).execute().data or []
    legacy_contact_rows = ready_query().is_("job_kind", "null").order("priority", desc=True).limit(limit).execute().data or []
    molecule_rows = ready_query().eq("job_kind", "MOLECULE_INTELLIGENCE").order("priority", desc=True).limit(limit).execute().data or []
    opportunity_rows = ready_query().eq("job_kind", "OPPORTUNITY_EVIDENCE").order("priority", desc=True).limit(2).execute().data or []
    rows = select_ready_agent_jobs(contact_rows + legacy_contact_rows + molecule_rows + opportunity_rows, limit=limit, contact_reserve=2)
    exported = []
    errors = []
    for job in rows:
        kind = str(job.get("job_kind") or "CONTACT_RESEARCH")
        title = f"[SVAK Research] {job.get('known_entities', {}).get('company', 'Molecule')} / {job.get('known_entities', {}).get('molecule', 'Molecule')} / {','.join(job.get('missing_dimensions') or [])}"
        if kind == "MOLECULE_INTELLIGENCE": title = f"[SVAK Molecule] {job.get('known_entities', {}).get('molecule', 'Molecule')} / {','.join(job.get('missing_dimensions') or [])}"
        if kind == "OPPORTUNITY_EVIDENCE": title = f"[SVAK Opportunity] {job.get('known_entities', {}).get('company', 'Company')} / {job.get('known_entities', {}).get('molecule', 'Molecule')} / {','.join(job.get('missing_dimensions') or [])}"
        try:
            for label in ("svak-work-ready", "svak-research", "priority-high" if int(job.get("priority") or 0) >= 85 else "priority-normal"):
                try:
                    _run_gh(["label", "create", label, "--color", "1d76db", "--force"], repo=repo)
                except Exception:
                    pass
            url = _run_gh(["issue", "create", "--title", title[:240], "--body", render_issue_body(job), "--label", "svak-work-ready", "--label", "svak-research", "--label", "priority-high" if int(job.get("priority") or 0) >= 85 else "priority-normal"], repo=repo)
            match = re.search(r"/(?:issues|pull)/(\d+)$", url)
            if not match:
                raise RuntimeError("github_issue_number_missing")
            number = int(match.group(1))
            client.table("agent_research_jobs").update({"github_issue_number": number, "github_issue_url": url, "exported_at": datetime.now(timezone.utc).isoformat(), "status": "EXPORTED"}).eq("id", job["id"]).execute()
            exported.append({"job_id": job["id"], "issue_number": number, "url": url})
        except Exception as exc:
            errors.append({"job_id": job.get("id"), "error": type(exc).__name__})
    if provider_usage is not None:
        provider_usage.record("chatgpt_work", jobs=len(exported))
    return {"status": "COMPLETED" if not errors else "PARTIAL", "exported": exported, "errors": errors}
