from impurity_leads.crawling.sitemap import extract_sitemap_urls


def test_extracts_loc_values():
    xml = "<urlset xmlns='http://www.sitemaps.org/schemas/sitemap/0.9'><url><loc>https://example.com/jobs</loc></url></urlset>"
    assert extract_sitemap_urls(xml) == ["https://example.com/jobs"]


def test_urlset_entries_are_sorted_newest_first():
    from impurity_leads.crawling.sitemap import parse_sitemap

    xml = """<urlset xmlns='http://www.sitemaps.org/schemas/sitemap/0.9'>
      <url><loc>https://example.com/old</loc><lastmod>2024-01-01</lastmod></url>
      <url><loc>https://example.com/undated</loc></url>
      <url><loc>https://example.com/new</loc><lastmod>2026-10-01T08:00:00+00:00</lastmod></url>
      <url><loc>https://example.com/bad-date</loc><lastmod>yesterday</lastmod></url>
    </urlset>"""
    sitemap = parse_sitemap(xml)
    assert sitemap.is_index is False
    assert sitemap.locations() == ["https://example.com/new", "https://example.com/old", "https://example.com/undated", "https://example.com/bad-date"]


def test_sitemap_index_lists_children_and_gzip_is_decompressed():
    import gzip
    from impurity_leads.crawling.sitemap import parse_sitemap

    xml = """<sitemapindex xmlns='http://www.sitemaps.org/schemas/sitemap/0.9'>
      <sitemap><loc>https://example.com/pages.xml</loc><lastmod>2025-01-01</lastmod></sitemap>
      <sitemap><loc>https://example.com/news.xml.gz</loc><lastmod>2026-01-01</lastmod></sitemap>
    </sitemapindex>"""
    sitemap = parse_sitemap(gzip.compress(xml.encode()))
    assert sitemap.is_index is True
    assert sitemap.locations() == ["https://example.com/news.xml.gz", "https://example.com/pages.xml"]


def test_oversized_gzip_and_entities_are_rejected():
    import gzip
    import pytest
    from impurity_leads.crawling.sitemap import parse_sitemap

    with pytest.raises(ValueError):
        parse_sitemap(gzip.compress(b"<urlset>" + b" " * 2048 + b"</urlset>"), max_bytes=1024)
    xml = "<!DOCTYPE x [<!ENTITY e SYSTEM 'file:///etc/passwd'>]><urlset><url><loc>&e;</loc></url></urlset>"
    assert "root:" not in "".join(parse_sitemap(xml).locations())
