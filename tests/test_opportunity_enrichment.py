from impurity_leads.agent_research import queue_opportunity_evidence_job, validate_agent_submission
from impurity_leads.opportunity_enrichment import rank_candidates, missing_opportunity_dimensions


class Result:
    def __init__(self, data=None):
        self.data = data or []


class Table:
    def __init__(self, rows=None):
        self.rows = list(rows or [])
        self.filters = []

    def select(self, *_): return self
    def eq(self, key, value): self.filters.append((key, "eq", value)); return self
    def in_(self, key, values): self.filters.append((key, "in", set(values))); return self
    def limit(self, *_): return self
    def order(self, *_args, **_kwargs): return self
    def execute(self):
        rows = self.rows
        for key, op, value in self.filters:
            rows = [row for row in rows if (row.get(key) == value if op == "eq" else row.get(key) in value)]
        self.filters = []
        return Result(rows)
    def insert(self, row):
        value = dict(row)
        value.setdefault("id", f"job-{len(self.rows)+1}")
        self.rows.append(value)
        return Result([value])


class Client:
    def __init__(self, jobs=None):
        self.tables = {"agent_research_jobs": Table(jobs)}

    def table(self, name): return self.tables.setdefault(name, Table())


def test_rank_candidates_prefers_nearest_qualification_then_signal_strength():
    rows = [
        {"company_id": "a", "molecule_id": "a", "candidate_score": 22, "candidate_signal_fingerprints": ["1"]},
        {"company_id": "b", "molecule_id": "b", "candidate_score": 44, "candidate_signal_fingerprints": ["1", "2"]},
    ]
    ranked = rank_candidates(rows, {"1": {"signal_type": "regulatory_application", "source_type": "regulatory"}, "2": {"signal_type": "impurity_characterization", "source_type": "publication"}})
    assert ranked[0]["company_id"] == "b"


def test_missing_dimensions_only_requests_opportunity_evidence():
    dims = missing_opportunity_dimensions([{"signal_type": "regulatory_application"}])
    assert dims[0] == "IMPURITY_CHARACTERIZATION"
    assert "CLINICAL_USE" not in dims


def test_queue_opportunity_evidence_job_is_pair_specific_and_deduped():
    client = Client()
    candidate = {"id": "candidate-1", "company_id": "company-1", "molecule_id": "molecule-1", "candidate_score": 44, "candidate_status": "UNQUALIFIED", "candidate_signal_fingerprints": ["fp"], "candidate_last_signal_at": "2026-09-16T00:00:00Z"}
    kwargs = dict(client=client, candidate=candidate, company_name="Sandoz", molecule_name="Tobramycin", missing_dimensions=["IMPURITY_CHARACTERIZATION"], priority=44)
    first = queue_opportunity_evidence_job(**kwargs)
    second = queue_opportunity_evidence_job(**kwargs)
    assert first["job_kind"] == "OPPORTUNITY_EVIDENCE"
    assert first["opportunity_id"] is None
    assert first["company_id"] == "company-1"
    assert second["id"] == first["id"]
    assert len(client.tables["agent_research_jobs"].rows) == 1


def _evidence_payload(job_id="job-1", **overrides):
    payload = {
        "job_id": job_id,
        "job_kind": "OPPORTUNITY_EVIDENCE",
        "company_id": "company-1",
        "molecule_id": "molecule-1",
        "research_summary": "A bounded result.",
        "evidence": [{
            "source_url": "https://example.org/paper",
            "source_title": "Impurity characterization",
            "publisher": "Example Journal",
            "source_date": "2024-01-01",
            "source_type": "publication",
            "signal_type": "IMPURITY_CHARACTERIZATION",
            "evidence_text": "The company reported impurity characterization for the molecule.",
            "company_specific": True,
            "molecule_specific": True,
            "confidence": 0.8,
        }],
        "sources": [{"url": "https://example.org/paper", "title": "Impurity characterization", "publisher": "Example Journal", "source_type": "publication", "suggested_source_class": "PRIMARY", "access_status": "PUBLIC"}],
        "missing_dimensions_resolved": ["IMPURITY_CHARACTERIZATION"],
        "remaining_unknowns": [],
        "recommended_next_queries": [],
    }
    payload.update(overrides)
    return payload


def test_opportunity_submission_requires_exact_context_and_drops_score_fields():
    result = validate_agent_submission(_evidence_payload(score_after=99, qualified=True), job_id="job-1", job_kind="OPPORTUNITY_EVIDENCE", job_context={"company_id": "company-1", "molecule_id": "molecule-1"})
    assert not result["valid"]
    assert "score_after" not in result["data"]
    assert any("computed" in item["message"] for item in result["errors"])


def test_generic_or_wrong_context_evidence_is_rejected_independently():
    payload = _evidence_payload(evidence=[
        {"source_url": "https://example.org/generic", "source_title": "Generic molecule", "publisher": "Example", "source_type": "publication", "signal_type": "IMPURITY_CHARACTERIZATION", "evidence_text": "The molecule is an antibiotic.", "company_specific": False, "molecule_specific": True, "confidence": 0.8},
        {"source_url": "https://example.org/good", "source_title": "Impurity characterization", "publisher": "Example", "source_type": "publication", "signal_type": "IMPURITY_CHARACTERIZATION", "evidence_text": "The company performed impurity characterization for the molecule.", "company_specific": True, "molecule_specific": True, "confidence": 0.8},
    ], sources=[
        {"url": "https://example.org/generic", "title": "Generic molecule", "publisher": "Example", "source_type": "publication", "suggested_source_class": "PRIMARY", "access_status": "PUBLIC"},
        {"url": "https://example.org/good", "title": "Impurity characterization", "publisher": "Example", "source_type": "publication", "suggested_source_class": "PRIMARY", "access_status": "PUBLIC"},
    ])
    result = validate_agent_submission(payload, job_id="job-1", job_kind="OPPORTUNITY_EVIDENCE", job_context={"company_id": "company-1", "molecule_id": "molecule-1"})
    assert result["valid"]
    assert len(result["data"]["evidence"]) == 1
    assert result["data"]["evidence"][0]["source_url"].endswith("/good")
