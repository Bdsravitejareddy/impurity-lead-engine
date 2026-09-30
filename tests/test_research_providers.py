from impurity_leads.research_providers import OfficialCompanyProvider, OfficialCompanyRequest


def test_official_provider_returns_normalized_candidate_with_bounded_urls():
    calls = []
    html = """<html><title>Quality</title><body><p>Vijayasarathi Ramaswami leads impurity characterization.</p></body></html>"""

    def fetcher(url):
        calls.append(url)
        return html

    request = OfficialCompanyRequest(
        contact_id="contact-1",
        contact_name="Vijayasarathi Ramaswami",
        company_name="Cipla Limited",
        company_domain="cipla.com",
        urls=(
            "https://www.cipla.com/leadership/vijayasarathi",
            "https://cipla.com/quality",
            "https://cipla.com/third",
        ),
        max_pages=2,
    )
    result = OfficialCompanyProvider().discover(request, fetcher)
    assert len(result.candidates) == 2
    assert calls == list(request.urls[:2])
    assert result.metrics == {"pages_attempted": 2, "pages_accepted": 2, "pages_failed": 0}
    assert result.candidates[0].source_type == "official_company"
    assert result.candidates[0].metadata["contact_name_match"] is True


def test_official_provider_records_fetch_failure_and_rejects_irrelevant_page():
    def fetcher(url):
        if url.endswith("/broken"):
            raise TimeoutError("timeout")
        return "<html><body><p>Company history only.</p></body></html>"

    request = OfficialCompanyRequest(
        contact_id="contact-1",
        contact_name="A Person",
        company_name="Example Pharma",
        company_domain="example.com",
        urls=("https://example.com/broken", "https://example.com/about"),
    )
    result = OfficialCompanyProvider().discover(request, fetcher)
    assert result.candidates == ()
    assert result.metrics == {"pages_attempted": 2, "pages_accepted": 0, "pages_failed": 1}
