from impurity_leads.research_discovery import PublicPatentProvider, SearchRequest


def test_public_patent_provider_extracts_bounded_public_links():
    html = '<a href="/patent/US123/en">Process impurity</a><a href="/patent/US124/en">Another</a>'
    results = PublicPatentProvider(lambda _: html).discover(SearchRequest(query="impurity", seed_type="MOLECULE", max_results=1))
    assert len(results) == 1
    assert results[0].source_type == "PATENT"
