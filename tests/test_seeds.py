from pathlib import Path

from impurity_leads.seeds import CompanySeed, load_company_seeds, relevant_candidate_urls


def test_load_company_seeds_parses_semicolon_molecules(tmp_path):
    path = tmp_path / "companies.csv"
    path.write_text("company_name,domain,molecules\nExample Pharma,example.com,Drug X;Drug Y\n")
    seeds = load_company_seeds(path)
    assert seeds[0].company_name == "Example Pharma"
    assert seeds[0].molecules == ["Drug X", "Drug Y"]


def test_load_company_seeds_ignores_repeated_header_rows(tmp_path):
    path = tmp_path / "companies.csv"
    path.write_text(
        "company_name,domain,molecules\n"
        "company_name,domain,molecules\n"
        "Indoco Remedies Limited,indoco.com,alogliptin benzoate\n"
    )

    seeds = load_company_seeds(path)

    assert seeds == [CompanySeed("Indoco Remedies Limited", "indoco.com", ["alogliptin benzoate"])]


def test_relevant_candidate_urls_combines_and_deduplicates():
    urls = relevant_candidate_urls(
        "example.com",
        sitemap_urls=["https://example.com/jobs/1", "https://example.com/privacy"],
        common_urls=["https://example.com/jobs/1", "https://example.com/tender/2"],
        cap=10,
    )
    assert "https://example.com/jobs/1" in urls
    assert "https://example.com/tender/2" in urls
    assert "https://example.com/privacy" not in urls
