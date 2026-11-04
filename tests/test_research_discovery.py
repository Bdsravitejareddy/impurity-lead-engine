from impurity_leads.research_discovery import EuropePmcProvider, SearchRequest, SearchResult, dedupe_results


def test_provider_normalizes_public_results_and_dedupes_urls():
    provider = EuropePmcProvider(lambda _: {"resultList": {"result": [{"pmid": "1", "title": "A"}, {"pmid": "2", "title": "B"}]}})
    results = provider.discover(SearchRequest(query="impurity", seed_type="MOLECULE"))
    assert len(results) == 2
    assert len(dedupe_results(results + [results[0]])) == 2
    assert results[0].source_type == "SCIENTIFIC_PUBLICATION"


def test_europe_pmc_preprint_links_use_its_own_source():
    provider = EuropePmcProvider(lambda _: {"resultList": {"result": [{"id": "PPR123", "source": "PPR", "title": "Preprint"}, {"id": "9", "pmid": "9", "source": "MED", "title": "Paper"}]}})
    urls = [row.url for row in provider.discover(SearchRequest(query="x", seed_type="t", max_results=5))]
    assert urls == ["https://europepmc.org/article/PPR/PPR123", "https://europepmc.org/article/MED/9"]
