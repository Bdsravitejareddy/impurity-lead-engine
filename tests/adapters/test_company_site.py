from pathlib import Path

from impurity_leads.adapters.company_site import CompanySiteAdapter


def test_job_page_emits_impurity_signal_for_known_molecule():
    html = Path("tests/fixtures/company_job.html").read_text()
    records = CompanySiteAdapter().parse_html("https://example.com/jobs/1", html, "Example Pharma", ["Drug X"])
    assert records
    assert records[0].molecule_name_raw == "Drug X"
    assert "impurity characterization" in records[0].signal_text.lower()


def test_vendor_page_is_marked_for_exclusion():
    html = Path("tests/fixtures/impurity_vendor.html").read_text()
    records = CompanySiteAdapter().parse_html("https://vendor.example/services", html, "Vendor Labs", [])
    assert records[0].metadata_json["is_impurity_vendor"] is True


def test_rfq_page_preserves_compact_direct_demand_evidence():
    html = Path("tests/fixtures/tender_rfq.html").read_text()
    records = CompanySiteAdapter().parse_html("https://example.com/tender/1", html, "Example Pharma", ["Drug X"])
    assert any("50 mg" in record.signal_text for record in records)


def _page(body, head=""):
    return f"<html><head>{head}</head><body>{body}</body></html>"


def test_molecule_names_match_whole_words_only():
    html = _page("<p>Our alanine program needs impurity characterization support.</p>")
    records = CompanySiteAdapter().parse_html("https://example.com/news/1", html, "Example Pharma", ["Ala", "ABC-12"])
    assert records and all(record.molecule_name_raw is None for record in records)
    html = _page("<p>ABC-123 requires impurity characterization.</p>")
    records = CompanySiteAdapter().parse_html("https://example.com/news/1", html, "Example Pharma", ["ABC-12", "ABC-123"])
    assert [record.molecule_name_raw for record in records] == ["ABC-123"]


def test_each_snippet_is_credited_to_its_nearest_molecule():
    filler = " ".join(["Lorem ipsum dolor sit amet."] * 30)
    html = _page(f"<p>Drug A needs a nitrosamine risk assessment.</p><p>{filler}</p><p>Drug B requires impurity characterization.</p>")
    records = CompanySiteAdapter().parse_html("https://example.com/news/1", html, "Example Pharma", ["Drug A", "Drug B"])
    credited = {record.molecule_name_raw: record.signal_text for record in records}
    assert "nitrosamine" in credited["Drug A"].lower()
    assert "impurity characterization" in credited["Drug B"].lower()


def test_published_at_prefers_article_meta_then_time_then_last_modified():
    adapter = CompanySiteAdapter()
    body = "<p>Drug X requires impurity characterization.</p><time datetime='2026-03-02'>2 March</time>"
    meta = "<meta property='article:published_time' content='2026-01-15T09:30:00+01:00'>"
    with_meta = adapter.parse_html("https://example.com/news/1", _page(body, meta), "Example Pharma", ["Drug X"])
    assert with_meta[0].published_at.isoformat() == "2026-01-15T09:30:00+01:00"
    with_time = adapter.parse_html("https://example.com/news/1", _page(body), "Example Pharma", ["Drug X"])
    assert with_time[0].published_at.isoformat() == "2026-03-02T00:00:00+00:00"
    plain = _page("<p>Drug X requires impurity characterization.</p><time datetime='soon'>x</time>")
    header = adapter.parse_html("https://example.com/news/1", plain, "Example Pharma", ["Drug X"],
                                last_modified="Wed, 21 Oct 2026 07:28:00 GMT")
    assert header[0].published_at.isoformat() == "2026-10-21T07:28:00+00:00"
    assert adapter.parse_html("https://example.com/news/1", plain, "Example Pharma", ["Drug X"])[0].published_at is None
