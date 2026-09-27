from datetime import datetime, timezone

from impurity_leads.enrichment_spike import Candidate, accept_evidence, run_spike, select_candidates
from impurity_leads.models import SourceRecord
import importlib.util


def _row(company_id, molecule_id, score=22, domain="example.com", latest="2026-09-01T00:00:00+00:00", types=None):
    return {
        "company_id": company_id, "molecule_id": molecule_id, "company": "Example Pharma",
        "molecule": "Drug X", "domain": domain, "score": score,
        "latest_event": latest, "signal_types": types or ["regulatory_application"],
        "source_url": "https://api.fda.gov/example", "source_record_id": "ANDA1",
        "excluded": False,
    }


def test_select_candidates_keeps_missing_domains_and_orders_deterministically():
    rows = [
        _row("z", "1", domain=""),
        _row("b", "2", latest="2026-09-03T00:00:00+00:00"),
        _row("a", "3", latest="2026-09-03T00:00:00+00:00"),
        _row("c", "4", score=40),
    ]

    selected = select_candidates(rows, limit=2)

    assert [(item.company_id, item.molecule_id) for item in selected] == [("a", "3"), ("b", "2")]


def test_local_domain_override_is_used_without_mutating_candidate_source_data():
    selected = select_candidates([_row("a", "3", domain="")], domain_overrides={"Example Pharma": "example.com"})

    assert selected[0].domain == "example.com"
    assert selected[0].stored_domain == ""
    assert selected[0].domain_override == "example.com"


def test_selection_report_marks_domain_optional_sources():
    candidate = select_candidates([_row("a", "3", domain="")])[0]

    report = candidate.selection_report()

    assert report["current_stored_domain"] == ""
    assert report["company_site_search_available"] is False
    assert report["publication_patent_regulatory_can_proceed_without_domain"] is True
    assert report["source_url"] == "https://api.fda.gov/example"


def test_accept_evidence_requires_explicit_company_molecule_and_technical_term():
    candidate = Candidate("c", "m", "Example Pharma", "Drug X", "example.com", 22)
    valid = SourceRecord(source_name="site", source_type="site", source_url="https://example.com/a",
                         fetched_at=datetime.now(timezone.utc), company_name_raw="Example Pharma",
                         molecule_name_raw="Drug X", signal_text="Drug X impurity characterization")
    generic = valid.model_copy(update={"signal_text": "Example Pharma latest news"})

    assert accept_evidence(candidate, valid) is True
    assert accept_evidence(candidate, generic) is False


def test_accept_evidence_allows_deterministic_parent_salt_equivalence():
    candidate = Candidate("c", "m", "Biocon Pharma", "Atorvastatin Calcium", "biocon.com", 22)
    record = SourceRecord(source_name="publication", source_type="publication", source_url="https://example.org/paper",
                          fetched_at=datetime.now(timezone.utc), company_name_raw="Biocon Pharma",
                          molecule_name_raw="Atorvastatin", signal_text="Biocon atorvastatin impurity method validation")

    assert accept_evidence(candidate, record) is True


def test_accept_evidence_does_not_match_unrelated_compounds():
    candidate = Candidate("c", "m", "Biocon Pharma", "Atorvastatin Calcium", "biocon.com", 22)
    record = SourceRecord(source_name="publication", source_type="publication", source_url="https://example.org/paper",
                          fetched_at=datetime.now(timezone.utc), company_name_raw="Biocon Pharma",
                          molecule_name_raw="Calcium Carbonate", signal_text="Biocon calcium carbonate impurity method validation")

    assert accept_evidence(candidate, record) is False


def test_spike_stops_after_first_promoted_candidate_and_enforces_page_bound():
    candidates = [Candidate(str(i), str(i), "Example Pharma", "Drug X", "example.com", 22) for i in range(3)]
    calls = []

    def enrich(candidate, max_pages, deadline):
        calls.append(candidate.company_id)
        record = SourceRecord(source_name="site", source_type="site", source_url=f"https://example.com/{candidate.company_id}",
                              fetched_at=datetime.now(timezone.utc), company_name_raw=candidate.company_name,
                              molecule_name_raw=candidate.molecule, signal_text="Drug X request for quotation impurity")
        return [(record, 1)] * (max_pages + 3)

    report = run_spike(candidates, enrich, max_pages=5, clock=lambda: 0.0)

    assert calls == ["0"]
    assert report["promoted"][0]["final_score"] >= 50
    assert report["promoted"][0]["pages"] == 5


def test_enrichment_uses_existing_weight_without_direct_bonus():
    candidate = Candidate("c", "m", "Example Pharma", "Drug X", "example.com", 22)

    def enrich(candidate, max_pages, deadline):
        yield SourceRecord(source_name="site", source_type="site", source_url="https://example.com/method",
                           fetched_at=datetime.now(timezone.utc), company_name_raw=candidate.company_name,
                           molecule_name_raw=candidate.molecule, signal_text="Drug X analytical method validation"), 1

    report = run_spike([candidate], enrich, max_pages=1, clock=lambda: 0.0)

    assert report["investigated"][0]["final_score"] == 38
    assert not report["promoted"]


def test_spike_reports_independent_source_family_statuses_after_zero_result():
    candidate = Candidate("c", "m", "Example Pharma", "Drug X", "example.com", 22)

    def enrich(candidate, max_pages, deadline):
        enrich.last_source_status = {
            "company_site": {"attempted": True, "status": "failed", "records": 0},
            "europe_pmc": {"attempted": True, "status": "no_match", "records": 0},
            "fda": {"attempted": True, "status": "records", "records": 1},
            "regulatory": {"attempted": False, "status": "not_configured", "records": 0},
        }
        return []

    report = run_spike([candidate], enrich)

    assert report["investigated"][0]["source_status"]["europe_pmc"]["status"] == "no_match"
    assert report["investigated"][0]["source_status"]["fda"]["records"] == 1


def test_failed_company_site_still_runs_later_source_families(monkeypatch):
    spec = importlib.util.spec_from_file_location("enrichment_script", "scripts/enrichment_spike.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    class Response:
        status_code = 200
        def json(self):
            return {"resultList": {"result": []}, "results": []}

    class Client:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def get(self, *args, **kwargs): return Response()

    monkeypatch.setattr(module, "create_crawl_client", lambda **kwargs: Client())
    monkeypatch.setattr(module.RobotsPolicy, "fetch", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("blocked")))
    candidate = Candidate("c", "m", "Example Pharma", "Drug X", "example.com", 22)

    list(module.enrich_candidate(candidate, 8, module.time.monotonic() + 30))

    assert module.enrich_candidate.last_source_status["company_site"]["status"] == "failed"
    assert module.enrich_candidate.last_source_status["europe_pmc"]["attempted"] is True
    assert module.enrich_candidate.last_source_status["fda"]["attempted"] is True
