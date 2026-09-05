import httpx

from impurity_leads.cli import fetch_structured_records, fixture_smoke_records, seconds_remaining


def test_budget_guard_returns_zero_after_deadline():
    assert seconds_remaining(start_monotonic=0.0, now_monotonic=60.0, deadline_minutes=1) == 0.0


def test_fixture_smoke_records_include_same_company_molecule_signals():
    records = fixture_smoke_records()
    pairs = {(record.company_name_raw, record.molecule_name_raw or record.active_ingredient_raw) for record in records}
    assert ("Example Pharma", "Drug X") in pairs


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload
    def raise_for_status(self):
        return None
    def json(self):
        return self.payload


class FakeClient:
    def get(self, url, params=None, headers=None):
        if "clinicaltrials.gov" in url:
            return FakeResponse({"studies": [{
                "protocolSection": {
                    "identificationModule": {"nctId": "NCT1", "briefTitle": "Trial of CT-1"},
                    "sponsorCollaboratorsModule": {"leadSponsor": {"name": "Clinical Co"}},
                    "designModule": {"phases": ["PHASE3"]},
                    "armsInterventionsModule": {"interventions": [{"type": "DRUG", "name": "CT-1"}]},
                    "statusModule": {"overallStatus": "RECRUITING"}
                }
            }]})
        return FakeResponse({"results": [{
            "application_number": "NDA1",
            "sponsor_name": "FDA Co",
            "products": [{"active_ingredients": [{"name": "FDA-1"}]}]
        }]})


def test_fetch_structured_records_reads_both_public_apis():
    records = fetch_structured_records(FakeClient())
    assert {(r.company_name_raw, r.molecule_name_raw) for r in records} == {
        ("Clinical Co", "CT-1"),
        ("FDA Co", "FDA-1"),
    }


def test_collect_daily_records_combines_structured_and_seeded_sources(tmp_path):
    from pathlib import Path

    from impurity_leads.cli import collect_daily_records
    from impurity_leads.config import Settings

    class IntegratedResponse:
        def __init__(self, *, payload=None, text="", status_code=200):
            self.payload = payload
            self.text = text
            self.status_code = status_code
            self.headers = {}

        def raise_for_status(self):
            if self.status_code >= 400:
                raise RuntimeError(self.status_code)

        def json(self):
            return self.payload

    class IntegratedClient:
        def get(self, url, params=None, headers=None):
            if "clinicaltrials.gov" in url:
                return IntegratedResponse(payload={"studies": [{
                    "protocolSection": {
                        "identificationModule": {"nctId": "NCT1", "briefTitle": "Trial of Drug X"},
                        "sponsorCollaboratorsModule": {"leadSponsor": {"name": "Example Pharma"}},
                        "designModule": {"phases": ["PHASE3"]},
                        "armsInterventionsModule": {"interventions": [{"type": "DRUG", "name": "Drug X"}]},
                        "statusModule": {"overallStatus": "RECRUITING"},
                    }
                }]})
            if "api.fda.gov" in url:
                return IntegratedResponse(payload={"results": []})
            if url.endswith("/robots.txt"):
                return IntegratedResponse(text="User-agent: *\nAllow: /\n")
            if url.endswith("/sitemap.xml"):
                return IntegratedResponse(text="<urlset><url><loc>https://example.com/jobs/1</loc></url></urlset>")
            if url.endswith("collinfo.json"):
                return IntegratedResponse(payload=[{"id": "CC-MAIN-2026-30"}])
            if "index.commoncrawl.org/CC-MAIN" in url:
                return IntegratedResponse(text='{"url":"https://example.com/tender/1"}\n')
            if url.endswith("/jobs/1"):
                return IntegratedResponse(text=Path("tests/fixtures/company_job.html").read_text())
            if url.endswith("/tender/1"):
                return IntegratedResponse(text=Path("tests/fixtures/tender_rfq.html").read_text())
            return IntegratedResponse(status_code=404)

    seed_path = tmp_path / "companies.csv"
    seed_path.write_text("company_name,domain,molecules\nExample Pharma,example.com,Drug X\n")
    records = collect_daily_records(
        IntegratedClient(),
        settings=Settings(per_domain_delay_seconds=0),
        seed_path=seed_path,
        sleep_fn=lambda _: None,
    )
    assert {record.source_type for record in records} >= {"trial", "job", "tender"}


def test_export_command_converts_opportunity_json_to_csv_and_xlsx(tmp_path):
    import json

    from impurity_leads.cli import main

    source = tmp_path / "opportunities.json"
    source.write_text(json.dumps([{
        "company_name": "Example Pharma",
        "molecule_name": "Drug X",
        "score": 88,
        "priority": "HOT",
        "likely_need_type": ["direct_impurity_rfq"],
        "rationale": "Direct RFQ evidence",
        "decision_maker_role": ["Analytical R&D"],
        "signal_fingerprints": ["abc"],
        "last_signal_at": None,
    }]))
    output_dir = tmp_path / "out"
    assert main(["export", str(source), "--output-dir", str(output_dir)]) == 0
    assert (output_dir / "opportunities.csv").exists()
    assert (output_dir / "opportunities.xlsx").exists()


def _opportunity_for_index(index: int, priority: str):
    from impurity_leads.models import Opportunity

    return Opportunity(
        company_name=f"Company {index}",
        molecule_name=f"Drug {index}",
        score=100 - (index % 20),
        priority=priority,
        likely_need_type=["nitrosamine/NDSRI"],
        rationale="x",
    )


def test_contact_enrichment_targets_only_hot_high_and_caps_at_30():
    from impurity_leads.cli import select_contact_enrichment_targets

    opportunities = [
        _opportunity_for_index(i, "REVIEW" if i % 5 == 0 else ("HOT" if i % 2 else "HIGH"))
        for i in range(45)
    ]
    selected = select_contact_enrichment_targets(opportunities, limit=30)
    assert len(selected) == 30
    assert all(item.priority in {"HOT", "HIGH"} for item in selected)
    assert selected == sorted(selected, key=lambda item: item.score, reverse=True)


def test_enrich_qualified_opportunities_fetches_public_contact_page(tmp_path):
    from pathlib import Path

    from impurity_leads.cli import enrich_qualified_opportunities
    from impurity_leads.config import Settings
    from impurity_leads.storage.memory import MemoryLeadStore

    class ContactResponse:
        def __init__(self, *, text="", payload=None, status_code=200):
            self.text = text
            self.payload = payload
            self.status_code = status_code
            self.headers = {}

        def json(self):
            return self.payload

        def raise_for_status(self):
            if self.status_code >= 400:
                raise RuntimeError(self.status_code)

    class ContactClient:
        def get(self, url, params=None, headers=None):
            if url.endswith("/robots.txt"):
                return ContactResponse(text="User-agent: *\nAllow: /\n")
            if url.endswith("/sitemap.xml"):
                return ContactResponse(text="<urlset><url><loc>https://example.com/about/leadership</loc></url></urlset>")
            if url.endswith("collinfo.json"):
                return ContactResponse(payload=[{"id": "CC-MAIN-2026-30"}])
            if "index.commoncrawl.org/CC-MAIN" in url:
                return ContactResponse(text="")
            if url.endswith("/about/leadership"):
                return ContactResponse(text=Path("tests/fixtures/contact_leadership.html").read_text())
            return ContactResponse(status_code=404)

    seeds = tmp_path / "companies.csv"
    seeds.write_text("company_name,domain,molecules\nExample Pharma,example.com,Drug X\n")
    opportunity = _opportunity_for_index(1, "HOT").model_copy(update={"company_name": "Example Pharma", "molecule_name": "Drug X"})
    store = MemoryLeadStore()
    mapping = enrich_qualified_opportunities(
        [opportunity],
        client=ContactClient(),
        settings=Settings(per_domain_delay_seconds=0),
        seed_path=seeds,
        store=store,
        sleep_fn=lambda _: None,
    )
    ranked = mapping[("Example Pharma", "Drug X")]
    assert ranked[0].contact.primary_email == "jane.smith@example.com"
    assert ranked[0].contact.email_status == "VERIFIED_PUBLIC"
    assert store.contacts
    assert store.opportunity_contacts


def test_contact_enrichment_failure_does_not_block_lead(tmp_path):
    from impurity_leads.cli import enrich_qualified_opportunities
    from impurity_leads.config import Settings
    from impurity_leads.storage.memory import MemoryLeadStore

    class BrokenClient:
        def get(self, url, params=None, headers=None):
            raise RuntimeError("temporary network failure")

    seeds = tmp_path / "companies.csv"
    seeds.write_text("company_name,domain,molecules\nExample Pharma,example.com,Drug X\n")
    opportunity = _opportunity_for_index(1, "HOT").model_copy(update={"company_name": "Example Pharma", "molecule_name": "Drug X"})
    mapping = enrich_qualified_opportunities(
        [opportunity],
        client=BrokenClient(),
        settings=Settings(per_domain_delay_seconds=0),
        seed_path=seeds,
        store=MemoryLeadStore(),
        sleep_fn=lambda _: None,
    )
    assert mapping == {}


def test_fetch_structured_records_uses_configured_json_headers_for_both_apis():
    from impurity_leads.config import Settings

    class RecordingClient(FakeClient):
        def __init__(self):
            self.headers_seen = []

        def get(self, url, params=None, headers=None):
            self.headers_seen.append((url, headers or {}))
            return super().get(url, params=params, headers=headers)

    client = RecordingClient()
    fetch_structured_records(
        client,
        Settings(user_agent="SVAK-Impurity-Lead-Research/0.1 (+ops@example.com)"),
    )

    assert len(client.headers_seen) == 2
    for _, headers in client.headers_seen:
        assert headers["Accept"] == "application/json"
        assert headers["User-Agent"].startswith("Mozilla/5.0")
        assert "SVAK-Impurity-Lead-Research/0.1 (+ops@example.com)" in headers["User-Agent"]


def test_fetch_structured_records_skips_forbidden_trials_and_keeps_fda(capsys):
    from impurity_leads.config import Settings

    class ForbiddenResponse:
        status_code = 403

        def raise_for_status(self):
            request = httpx.Request("GET", "https://clinicaltrials.gov/api/v2/studies")
            response = httpx.Response(403, request=request)
            raise httpx.HTTPStatusError("forbidden", request=request, response=response)

        def json(self):
            return {}

    class ResilientClient(FakeClient):
        def get(self, url, params=None, headers=None):
            if "clinicaltrials.gov" in url:
                return ForbiddenResponse()
            return super().get(url, params=params, headers=headers)

    records = fetch_structured_records(ResilientClient(), Settings())

    assert {(r.company_name_raw, r.molecule_name_raw) for r in records} == {("FDA Co", "FDA-1")}
    assert "clinical_trials=skipped status=403" in capsys.readouterr().out


def test_fetch_structured_records_skips_forbidden_fda_and_keeps_trials(capsys):
    from impurity_leads.config import Settings

    class ForbiddenResponse:
        status_code = 403

        def raise_for_status(self):
            request = httpx.Request("GET", "https://api.fda.gov/drug/drugsfda.json")
            response = httpx.Response(403, request=request)
            raise httpx.HTTPStatusError("forbidden", request=request, response=response)

        def json(self):
            return {}

    class ResilientClient(FakeClient):
        def get(self, url, params=None, headers=None):
            if "api.fda.gov" in url:
                return ForbiddenResponse()
            return super().get(url, params=params, headers=headers)

    records = fetch_structured_records(ResilientClient(), Settings())

    assert {(r.company_name_raw, r.molecule_name_raw) for r in records} == {("Clinical Co", "CT-1")}
    assert "fda=skipped status=403" in capsys.readouterr().out
