from impurity_leads.crawling.sitemap import extract_sitemap_urls


def test_extracts_loc_values():
    xml = "<urlset xmlns='http://www.sitemaps.org/schemas/sitemap/0.9'><url><loc>https://example.com/jobs</loc></url></urlset>"
    assert extract_sitemap_urls(xml) == ["https://example.com/jobs"]
