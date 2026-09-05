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
