from impurity_leads.research_graph import ResearchBudget, bounded_query_plan, extract_claims, fuse_claims, normalize_entity_name, publication_graph_entities


def test_graph_names_and_queries_are_normalized_and_bounded():
    assert normalize_entity_name(" Cobimetinib, API ") == "cobimetinib api"
    queries = bounded_query_plan([{"entity_type": "MOLECULE", "name": "Cobimetinib"}], ResearchBudget(max_queries=3))
    assert len(queries) == 3
    assert queries[0]["depth"] == 1
    assert len({item["query"].casefold() for item in queries}) == len(queries)


def test_claim_extraction_is_source_linked_and_fusion_preserves_support():
    claims = extract_claims("The paper reports impurity and stability method validation.", source_id="s1", source_url="https://example.test/paper")
    assert claims and all(item["source_id"] == "s1" and item["provenance"] == "OBSERVED" for item in claims)
    fused = fuse_claims([{**claims[0], "entity": "Cobimetinib"}, {**claims[0], "entity": "Cobimetinib", "source_id": "s2"}])
    assert fused[0]["supporting_sources"] == ["s1", "s2"]


def test_ai_analysis_is_disabled_by_default_without_network_call():
    from impurity_leads.ai_analysis import analyze_json
    from impurity_leads.config import Settings
    assert analyze_json(Settings(), instructions="return json", document="text", schema={"type": "object"}) is None


def test_publication_graph_entities_are_canonical_and_typed():
    rows = publication_graph_entities(person="Vijayasarathi R", company="Cipla", title="Impurity method")
    assert {row["entity_type"] for row in rows} == {"PERSON", "COMPANY", "PUBLICATION"}
    assert next(row for row in rows if row["entity_type"] == "PERSON")["normalized_name"] == "vijayasarathi r"
