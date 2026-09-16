from impurity_leads.agent_github import (
    AGENT_JOB_END,
    AGENT_JOB_START,
    WORK_RESULT_END,
    WORK_RESULT_START,
    build_issue_payload,
    extract_job_payload,
    extract_marked_json,
    render_issue_body,
    select_ready_agent_jobs,
)


def job():
    return {
        "id": "job-1", "opportunity_id": "opp-1", "priority": 100,
        "known_entities": {"company": "ROCHE", "molecule": "COBIMETINIB", "opportunity_score": 100},
        "quality_before": {"best_contact_score": 52.2}, "missing_dimensions": ["PERSON_IDENTITY"],
        "research_goal": "Resolve identity",
    }


def test_issue_body_contains_bounded_machine_payload_and_no_secret():
    body = render_issue_body(job())
    assert AGENT_JOB_START in body and AGENT_JOB_END in body
    assert "ROCHE" in body and "COBIMETINIB" in body
    assert "SUPABASE_SECRET_KEY" not in body
    payload, error = extract_job_payload(body)
    assert error is None and payload["agent_job_id"] == "job-1"


def test_molecule_issue_payload_is_job_kind_aware():
    payload = build_issue_payload({"id": "job-m", "job_kind": "MOLECULE_INTELLIGENCE", "molecule_id": "mol-1", "known_entities": {"molecule": "Cobimetinib"}})
    assert payload["job_kind"] == "MOLECULE_INTELLIGENCE"
    assert payload["molecule_id"] == "mol-1"


def test_marked_work_result_extracts_only_json():
    result = {"job_id": "job-1", "people": [], "sources": []}
    value, error = extract_marked_json(f"noise\n{WORK_RESULT_START}\n{{\"job_id\":\"job-1\",\"people\":[],\"sources\":[]}}\n{WORK_RESULT_END}\nnoise")
    assert error is None and value == result


def test_unmarked_or_malformed_comment_is_ignored():
    value, error = extract_marked_json("{\"job_id\": \"job-1\"}")
    assert value is None and error == "markers_missing"
    value, error = extract_marked_json(f"{WORK_RESULT_START}{{bad}}{WORK_RESULT_END}")
    assert value is None and error == "invalid_json"


def test_ready_job_selection_reserves_capacity_for_contact_research():
    rows = [
        {"id": "m1", "job_kind": "MOLECULE_INTELLIGENCE", "priority": 100},
        {"id": "m2", "job_kind": "MOLECULE_INTELLIGENCE", "priority": 99},
        {"id": "m3", "job_kind": "MOLECULE_INTELLIGENCE", "priority": 98},
        {"id": "c1", "job_kind": "CONTACT_RESEARCH", "priority": 70},
        {"id": "c2", "job_kind": "CONTACT_RESEARCH", "priority": 60},
    ]
    selected = select_ready_agent_jobs(rows, limit=5, contact_reserve=2)
    assert [row["id"] for row in selected[:2]] == ["c1", "c2"]
    assert {row["job_kind"] for row in selected} == {"CONTACT_RESEARCH", "MOLECULE_INTELLIGENCE"}


def test_ready_job_selection_caps_opportunity_evidence_and_keeps_fair_share():
    rows = [
        {"id": "c1", "job_kind": "CONTACT_RESEARCH", "priority": 10},
        {"id": "m1", "job_kind": "MOLECULE_INTELLIGENCE", "priority": 100},
        {"id": "o1", "job_kind": "OPPORTUNITY_EVIDENCE", "priority": 99},
        {"id": "o2", "job_kind": "OPPORTUNITY_EVIDENCE", "priority": 98},
        {"id": "o3", "job_kind": "OPPORTUNITY_EVIDENCE", "priority": 97},
    ]
    selected = select_ready_agent_jobs(rows, limit=5, contact_reserve=1)
    assert {row["job_kind"] for row in selected} >= {"CONTACT_RESEARCH", "MOLECULE_INTELLIGENCE"}
    assert sum(row["job_kind"] == "OPPORTUNITY_EVIDENCE" for row in selected) == 2
