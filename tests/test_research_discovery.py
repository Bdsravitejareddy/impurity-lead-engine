from impurity_leads.research_discovery import EuropePmcProvider, SearchRequest, SearchResult, dedupe_results


def test_provider_normalizes_public_results_and_dedupes_urls():
    provider = EuropePmcProvider(lambda _: {"resultList": {"result": [{"pmid": "1", "title": "A"}, {"pmid": "2", "title": "B"}]}})
    results = provider.discover(SearchRequest(query="impurity", seed_type="MOLECULE"))
    assert len(results) == 2
    assert len(dedupe_results(results + [results[0]])) == 2
    assert results[0].source_type == "SCIENTIFIC_PUBLICATION"
