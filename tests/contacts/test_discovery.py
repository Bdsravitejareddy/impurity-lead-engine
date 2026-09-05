from impurity_leads.contacts.discovery import contact_candidate_urls


def test_contact_url_discovery_prefers_leadership_and_rd_paths():
    urls = [
        "https://example.com/products",
        "https://example.com/about/leadership",
        "https://example.com/research/analytical",
        "https://other.com/team",
    ]
    selected = contact_candidate_urls(urls, "example.com", limit=2)
    assert selected == [
        "https://example.com/about/leadership",
        "https://example.com/research/analytical",
    ]


def test_contact_url_discovery_deduplicates_and_stays_same_domain():
    urls = [
        "https://www.example.com/team",
        "https://example.com/team",
        "https://example.com/contact",
        "https://other.com/leadership",
    ]
    selected = contact_candidate_urls(urls, "example.com", limit=12)
    assert all("example.com" in item for item in selected)
    assert len(selected) == 2
