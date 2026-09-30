from types import SimpleNamespace

from impurity_leads.contact_research import (
    _analysis_for,
    _identity,
    _queries,
    _terminal_source,
    name_variants,
    official_company_urls,
    opportunity_link_payload,
    official_source_payload,
    _run_official_company_research,
    resolve_identity,
    run_pending_contact_research,
)


class _Result:
    def __init__(self, data):
        self.data = data


class _Table:
    def __init__(self, rows=None, name=""):
        self.rows = rows or []
        self.name = name
        self.filters = []

    def select(self, *_): return self
    def eq(self, key, value): self.filters.append((key, "eq", value)); return self
    def gte(self, key, value): self.filters.append((key, "gte", value)); return self
    def neq(self, key, value): self.filters.append((key, "neq", value)); return self
    def order(self, *_args, **_kwargs): return self
    def limit(self, value): self._limit = value; return self

    def execute(self):
        rows = self.rows
        for key, op, value in self.filters:
            rows = [row for row in rows if (row.get(key) == value if op == "eq" else row.get(key, 0) >= value if op == "gte" else row.get(key) != value)]
        self.filters = []
        return _Result(rows[:getattr(self, "_limit", len(rows))])

    def upsert(self, row, on_conflict=None):
        keys = [key.strip() for key in (on_conflict or "").split(",") if key]
        existing = next((item for item in self.rows if keys and all(item.get(key) == row.get(key) for key in keys)), None)
        if existing:
            existing.update(row)
        else:
            item = dict(row)
            item.setdefault("id", f"{self.name}-{len(self.rows) + 1}")
            self.rows.append(item)
        return self

    def insert(self, row):
        item = dict(row)
        item.setdefault("id", f"{self.name}-{len(self.rows) + 1}")
        self.rows.append(item)
        return self


class _Client:
    def __init__(self):
        self.tables = {
            "companies": _Table([{"id": "company-1", "domain": "cipla.com", "legal_name": "Cipla Limited"}], "companies"),
            "contact_sources": _Table([], "contact_sources"),
            "opportunities": _Table([{"id": "opp-1", "company_id": "company-1", "score": 90, "status": "new"}], "opportunities"),
        }

    def table(self, name):
        return self.tables.setdefault(name, _Table([], name))


def test_identity_requires_two_name_tokens_for_high_match():
    contact = {"display_name": "Keisuke Inoue"}
    assert _identity(contact, {"authorString": "Keisuke Inoue; Takeda"}) == "HIGH"
    assert _identity(contact, {"authorString": "Keisuke Smith"}) == "MEDIUM"
    assert _identity(contact, {"authorString": "Someone Else"}) in {"LOW", "REJECTED"}


def test_abbreviated_professional_name_uses_contextual_resolution():
    contact = {"display_name": "Vijayasarathi Ramaswami", "company": "Cipla", "department": "Global Quality"}
    candidate = {"displayName": "Vijayasarathi R", "company": "Cipla", "title": "Global Head of Quality"}
    result = resolve_identity(contact, candidate)
    assert result["state"] in {"CONFIRMED_MATCH", "PROBABLE_MATCH"}
    assert result["confidence"] >= 70
    assert "surname initial is compatible" in result["supporting_evidence"]


def test_common_name_requires_context_and_does_not_merge_on_name_only():
    result = resolve_identity({"display_name": "Jitendra Singh", "company": "Cipla"}, {"displayName": "Jitendra Singh", "company": "Unrelated Pharma"})
    assert result["state"] == "REJECTED_MATCH"
    assert result["confidence"] < 50
    same_company_without_role = resolve_identity({"display_name": "Jitendra Singh", "company": "Cipla"}, {"displayName": "Jitendra Singh", "company": "Cipla"})
    assert same_company_without_role["state"] == "NEEDS_REVIEW"


def test_name_variants_are_bounded_and_useful():
    variants = name_variants("Dr. Vijayasarathi Ramaswami")
    assert "Vijayasarathi Ramaswami" in variants
    assert "vijayasarathi R" in variants
    assert "V Ramaswami" in variants
    assert "V. Ramaswami" in variants
    assert "vijayasarathi R Ramaswami" not in variants
    assert len(variants) <= 4


def test_queries_are_bounded_and_deduplicated():
    queries = _queries({"display_name": "Keisuke Inoue"}, [{"extraction_json": {"keywords": ["analytical", "analytical", "CMC"], "currentCompany": "Takeda"}}])
    assert len(queries) <= 20
    assert len(queries) == len(set(q.lower() for q in queries))
    assert any("publication" in query for query in queries)


def test_worker_skips_without_backend_credentials():
    result = run_pending_contact_research(SimpleNamespace(supabase_url=None, supabase_secret_key=None))
    assert result["status"] == "SKIPPED"


def test_analysis_is_conservative_and_provenanced():
    themes, problems, jtbd = _analysis_for("A stability-indicating analytical method addressed impurity validation.", "source-1")
    assert themes and problems and jtbd
    assert all(row["source_ids"] == ["source-1"] for row in themes + problems + jtbd)
    assert all(row["provenance"] == "INFERRED" for row in jtbd)


def test_terminal_source_records_final_disposition():
    row = _terminal_source(contact_id="c", url="https://europepmc.org/article/MED/1", title="Paper", source_date=None, query="person publication", result={"authorString": "A Person"}, status="REJECTED", reason="WRONG_PERSON", technical=False, identity="LOW")
    assert row["status"] == "REJECTED"
    assert row["rejection_reason"] == "WRONG_PERSON"
    assert row["extraction_json"]["identity"] == "LOW"


def test_official_company_urls_are_bounded_and_domain_scoped():
    urls = official_company_urls("cipla.com")
    assert len(urls) <= 6
    assert urls[0] == "https://cipla.com/about"
    assert all(url.startswith("https://cipla.com/") for url in urls)


def test_official_source_payload_preserves_provenance_and_contact_context():
    payload = official_source_payload(
        contact_id="contact-1",
        candidate={
            "url": "https://cipla.com/quality",
            "title": "Quality",
            "source_type": "official_company",
            "signal_text": "Impurity characterization is part of the quality program.",
            "metadata": {"contact_name_match": True, "source_class": "PRIMARY"},
        },
    )
    assert payload["contact_id"] == "contact-1"
    assert payload["status"] == "USED"
    assert payload["source_kind"] == "EXTERNAL_RESEARCH"
    assert payload["extraction_json"]["attribution"] == "PERSON_DIRECT"


def test_ambiguous_opportunity_link_is_not_constructed():
    assert opportunity_link_payload("opp-1", "contact-1", "source-1", identity_state="NEEDS_REVIEW") is None
    payload = opportunity_link_payload("opp-1", "contact-1", "source-1", identity_state="CONFIRMED_MATCH")
    assert payload["source_ids"] == ["source-1"]


def test_official_worker_persists_evidence_and_is_idempotent():
    client = _Client()
    contact = {"id": "contact-1", "company_id": "company-1", "display_name": "Vijayasarathi Ramaswami", "title": "Global Head of Quality"}
    html = "<html><title>Quality</title><body><p>Vijayasarathi Ramaswami leads impurity characterization.</p></body></html>"
    first = _run_official_company_research(client, contact, SimpleNamespace(), page_fetcher=lambda url: html)
    second = _run_official_company_research(client, contact, SimpleNamespace(), page_fetcher=lambda url: html)
    assert first["sources_used"] == 6 and first["links_created"] == 1
    assert second["sources_used"] == 0 and second["links_created"] == 0
    assert len(client.tables["contact_sources"].rows) == 6
    assert len(client.tables["contact_claims"].rows) == 6
    assert len(client.tables["contact_works"].rows) == 6
    assert len(client.tables["opportunity_contacts"].rows) == 1


def test_official_worker_reports_company_lookup_failure_without_throwing():
    class BrokenClient:
        def table(self, name):
            raise RuntimeError("company lookup unavailable")

    result = _run_official_company_research(
        BrokenClient(),
        {"id": "contact-1", "company_id": "company-1", "display_name": "A Person"},
        SimpleNamespace(),
        page_fetcher=lambda url: "",
    )
    assert result["pages_failed"] == 1
    assert result["sources_used"] == 0
