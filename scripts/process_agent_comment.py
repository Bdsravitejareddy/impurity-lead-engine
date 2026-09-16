"""Process one marked GitHub Work result comment through staging/validation."""
from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from supabase import create_client

from impurity_leads.agent_github import extract_job_payload, extract_marked_json
from impurity_leads.agent_research import apply_validated_agent_research, validate_agent_submission


def _gh(args: list[str], repo: str) -> None:
    env = os.environ.copy(); env["GH_REPO"] = repo
    subprocess.run(["gh", *args], check=False, capture_output=True, text=True, env=env, timeout=30)


def main() -> int:
    event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())
    repo = os.environ.get("GITHUB_REPOSITORY", "Bdsravitejareddy/impurity-lead-engine")
    issue = event.get("issue") or {}
    comment = event.get("comment") or {}
    if issue.get("pull_request") or "svak-work-ready" not in [label.get("name") for label in issue.get("labels") or []]:
        return 0
    job_payload, error = extract_job_payload(issue.get("body") or "")
    if error:
        return 0
    result, error = extract_marked_json(comment.get("body") or "")
    if error or not isinstance(result, dict):
        return 0
    settings = {"url": os.environ.get("SUPABASE_URL"), "key": os.environ.get("SUPABASE_SECRET_KEY")}
    if not settings["url"] or not settings["key"]:
        print(json.dumps({"event": "agent_result_failed", "reason": "supabase_credentials_missing"}))
        return 1
    client = create_client(settings["url"], settings["key"])
    job_id = str(job_payload["agent_job_id"])
    job_rows = client.table("agent_research_jobs").select("*").eq("id", job_id).limit(1).execute().data or []
    if not job_rows:
        return 0
    job = job_rows[0]
    comment_id = int(comment.get("id") or 0)
    duplicates = client.table("agent_research_submissions").select("id").eq("github_issue_number", issue.get("number")).eq("github_comment_id", comment_id).limit(1).execute().data or []
    validation = validate_agent_submission(result, job_id=job_id, job_kind=str(job.get("job_kind") or "CONTACT_RESEARCH"), job_context=job, seen_submission=bool(duplicates))
    submission = client.table("agent_research_submissions").insert({"agent_job_id": job_id, "submitted_at": datetime.now(timezone.utc).isoformat(), "raw_result_json": validation.get("data") or result, "schema_valid": bool(validation.get("valid")), "validation_status": "VALID" if validation.get("valid") else "REJECTED", "validation_errors": validation.get("errors") or [], "source_channel": "CHATGPT_WORK_GITHUB", "github_issue_number": issue.get("number"), "github_comment_id": comment_id, "github_comment_url": f"https://github.com/{repo}/issues/{issue.get('number')}#issuecomment-{comment_id}"}).select("id").execute()
    if not validation.get("valid"):
        client.table("agent_research_jobs").update({"status": "REJECTED", "completed_at": datetime.now(timezone.utc).isoformat(), "metrics": {"validation_errors": validation.get("errors") or []}}).eq("id", job_id).execute()
        _gh(["issue", "comment", str(issue["number"]), "--body", "SVAK validation rejected this Work result as malformed or unsafe. See staged validation errors."], repo)
        return 0
    client.table("agent_research_jobs").update({"status": "VALIDATING", "submitted_at": datetime.now(timezone.utc).isoformat()}).eq("id", job_id).execute()
    metrics = apply_validated_agent_research(client, job=job, validated=validation)
    client.table("agent_research_submissions").update({"processed_at": datetime.now(timezone.utc).isoformat(), "validation_status": "VALID"}).eq("id", (submission.data or [{}])[0].get("id")).execute()
    terminal_status = "APPLIED" if metrics.get("status") in {"APPLIED", "COMPLETED"} else "PARTIAL"
    client.table("agent_research_jobs").update({"status": terminal_status, "validated_at": datetime.now(timezone.utc).isoformat(), "completed_at": datetime.now(timezone.utc).isoformat(), "last_attempt_at": datetime.now(timezone.utc).isoformat(), "attempt_count": int(job.get("attempt_count") or 0), "last_outcome": metrics.get("outcome"), "metrics": metrics}).eq("id", job_id).execute()
    _gh(["issue", "comment", str(issue["number"]), "--body", "SVAK validation complete.\n\nStatus: " + terminal_status + "\n" + json.dumps(metrics, sort_keys=True)], repo)
    _gh(["label", "create", "svak-work-applied", "--color", "0e8a16", "--force"], repo)
    _gh(["issue", "edit", str(issue["number"]), "--remove-label", "svak-work-ready", "--add-label", "svak-work-applied"], repo)
    if terminal_status == "APPLIED":
        _gh(["issue", "close", str(issue["number"]), "--comment", "SVAK marked this job applied."], repo)
    print(json.dumps({"event": "agent_result_applied", "job_id": job_id, **metrics}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
