from impurity_leads.official_company import is_company_url, parse_official_company_html


def test_company_url_accepts_company_subdomains_but_rejects_lookalikes():
    assert is_company_url("https://www.cipla.com/leadership", "cipla.com")
    assert is_company_url("https://research.cipla.com/pipeline", "cipla.com")
    assert not is_company_url("https://cipla.com.evil.example/leadership", "cipla.com")
    assert not is_company_url("https://example.com/cipla", "cipla.com")


def test_official_page_emits_source_backed_contact_and_technical_evidence():
    html = """
    <html><head><title>Global Quality Leadership</title></head>
    <body><nav>Home Careers</nav>
    <main><h1>Vijayasarathi Ramaswami</h1>
    <p>Global Head of Quality overseeing impurity characterization and stability programs.</p>
    </main></body></html>
    """
    records = parse_official_company_html(
        "https://www.cipla.com/leadership/vijayasarathi",
        html,
        company_name="Cipla Limited",
        company_domain="cipla.com",
        contact_name="Vijayasarathi Ramaswami",
    )
    assert len(records) == 1
    record = records[0]
    assert record.source_type == "official_company"
    assert record.company_domain_raw == "cipla.com"
    assert record.metadata_json["contact_name_match"] is True
    assert record.metadata_json["page_title"] == "Global Quality Leadership"
    assert "impurity characterization" in record.signal_text.lower()


def test_official_parser_rejects_non_company_and_vendor_pages():
    vendor_html = "<html><body><p>Custom impurity synthesis and reference standards.</p></body></html>"
    assert parse_official_company_html(
        "https://vendor.example/services", vendor_html, "Cipla", "cipla.com"
    ) == []
    assert parse_official_company_html(
        "https://www.cipla.com/about", "<html><body><p>Company history.</p></body></html>", "Cipla", "cipla.com"
    ) == []
