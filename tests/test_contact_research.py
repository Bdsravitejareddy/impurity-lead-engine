from types import SimpleNamespace

from impurity_leads.contact_research import _analysis_for, _identity, _queries, _terminal_source, name_variants, resolve_identity, run_pending_contact_research


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


def test_name_variants_are_bounded_and_useful():
    variants = name_variants("Dr. Vijayasarathi Ramaswami")
    assert "vijayasarathi ramaswami" in variants
    assert "vijayasarathi R" in variants
    assert "V Ramaswami" in variants
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
