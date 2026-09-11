from impurity_leads.agent_research import (
    active_agent_dedupe_key,
    build_agent_research_prompt,
    queue_agent_research_job,
    validate_agent_submission,
)


class Result:
    def __init__(self, data=None):
        self.data = data or []


class Table:
    def __init__(self):
        self.rows = []
        self.filters = {}

    def select(self, *_): return self
    def eq(self, key, value): self.filters[key] = value; return self
    def in_(self, key, values): self.filters[key] = set(values); return self
    def limit(self, *_): return self
    def execute(self):
        rows = [row for row in self.rows if all((row.get(k) in v if isinstance(v, set) else row.get(k) == v) for k, v in self.filters.items())]
        self.filters = {}
        return Result(rows)
    def insert(self, row): self.rows.append(dict(row)); return self


class Client:
    def __init__(self): self.tables = {"agent_research_jobs": Table()}
    def table(self, name): return self.tables.setdefault(name, Table())


def test_alias_dedupe_key_is_stable():
    assert active_agent_dedupe_key("opp-1", ["CURRENT_ROLE", "PERSON_IDENTITY"]) == "opp-1:CURRENT_ROLE,PERSON_IDENTITY"


def test_prompt_is_bounded_and_restricts_agent():
    prompt = build_agent_research_prompt({"known_entities": {"company": "Cipla", "molecule": "Cobimetinib", "opportunity_score": 94}, "missing_dimensions": ["PERSON_IDENTITY"]})
    assert "Cipla" in prompt and "Cobimetinib" in prompt
    assert "Do not bypass authentication" in prompt
    assert "source_urls" in prompt


def test_quality_fail_creates_one_ready_job_and_duplicate_is_reused():
    client = Client()
    args = dict(targeted_job={"id": "target-1"}, opportunity={"id": "opp-1", "company_name": "Cipla", "molecule_name": "Cobimetinib", "score": 94}, missing_dimensions=["PERSON_IDENTITY"], quality_before={"best_contact_score": 42})
    first = queue_agent_research_job(client, **args)
    second = queue_agent_research_job(client, **args)
    assert first["status"] == "READY"
    assert first["id"] if "id" in first else True
    assert second["dedupe_key"] == first["dedupe_key"]
    assert len(client.tables["agent_research_jobs"].rows) == 1


def test_source_free_observed_claim_is_not_accepted_as_observed():
    result = validate_agent_submission({"job_id": "job-1", "people": [{"full_name": "A Person", "claims": [{"claim": "works at Cipla", "proposed_provenance": "OBSERVED", "source_urls": []}]}], "sources": []}, job_id="job-1")
    assert not result["valid"]
    assert result["data"]["people"][0]["claims"][0]["proposed_provenance"] == "INFERRED"


def test_masked_email_cannot_be_verified_public():
    result = validate_agent_submission({"job_id": "job-1", "people": [{"full_name": "A Person", "contactability": {"status": "VERIFIED_PUBLIC", "email": "a***@example.com"}}], "sources": []}, job_id="job-1")
    assert not result["valid"]
    assert result["data"]["people"][0]["contactability"]["status"] == "UNKNOWN"


def test_invalid_json_is_rejected_safely():
    result = validate_agent_submission("{bad", job_id="job-1")
    assert result["valid"] is False
