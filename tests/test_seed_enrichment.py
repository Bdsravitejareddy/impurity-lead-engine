from pathlib import Path

from impurity_leads.cli import fetch_seeded_company_records
from impurity_leads.config import Settings


class FakeResponse:
    def __init__(self, text="", json_data=None, status_code=200):
        self.text = text
        self._json = json_data
        self.status_code = status_code
        self.headers = {}
    def json(self):
        return self._json
    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


class FakeClient:
    def get(self, url, params=None, headers=None):
        if url.endswith("/robots.txt"):
            return FakeResponse("User-agent: *\nAllow: /\n")
        if url.endswith("/sitemap.xml"):
            return FakeResponse("<urlset><url><loc>https://example.com/jobs/1</loc></url></urlset>")
        if url.endswith("collinfo.json"):
            return FakeResponse(json_data=[{"id": "CC-MAIN-2026-30"}])
        if "index.commoncrawl.org/CC-MAIN" in url:
            return FakeResponse('{"url":"https://example.com/tender/1"}\n')
        if url.endswith("/jobs/1"):
            return FakeResponse(Path("tests/fixtures/company_job.html").read_text())
        if url.endswith("/tender/1"):
            return FakeResponse(Path("tests/fixtures/tender_rfq.html").read_text())
        return FakeResponse(status_code=404)


def test_seed_enrichment_combines_sitemap_and_common_crawl(tmp_path):
    seeds = tmp_path / "companies.csv"
    seeds.write_text("company_name,domain,molecules\nExample Pharma,example.com,Drug X\n")
    records = fetch_seeded_company_records(
        FakeClient(),
        seed_path=seeds,
        settings=Settings(per_domain_delay_seconds=0),
        sleep_fn=lambda _: None,
    )
    assert {record.source_type for record in records} >= {"job", "tender"}


def test_seed_enrichment_stops_before_network_when_deadline_exhausted(tmp_path):
    class CountingClient:
        def __init__(self):
            self.calls = 0

        def get(self, url, params=None, headers=None):
            self.calls += 1
            raise AssertionError("network should not be scheduled after deadline")

    seeds = tmp_path / "companies.csv"
    seeds.write_text("company_name,domain,molecules\nExample Pharma,example.com,Drug X\n")
    client = CountingClient()
    records = fetch_seeded_company_records(
        client,
        seed_path=seeds,
        settings=Settings(per_domain_delay_seconds=0),
        sleep_fn=lambda _: None,
        deadline_monotonic=10.0,
        monotonic_fn=lambda: 11.0,
    )
    assert records == []
    assert client.calls == 0


def test_contact_enrichment_respects_deadline_before_network(tmp_path):
    from impurity_leads.cli import enrich_qualified_opportunities
    from impurity_leads.models import Opportunity
    from impurity_leads.storage.memory import MemoryLeadStore

    class CountingClient:
        def __init__(self):
            self.calls = 0
        def get(self, url, params=None, headers=None):
            self.calls += 1
            raise AssertionError("network should not be scheduled after deadline")

    seeds = tmp_path / "companies.csv"
    seeds.write_text("company_name,domain,molecules\nExample Pharma,example.com,Drug X\n")
    opportunity = Opportunity(
        company_name="Example Pharma", molecule_name="Drug X", score=90, priority="HOT",
        likely_need_type=["nitrosamine/NDSRI"], rationale="x"
    )
    client = CountingClient()
    mapping = enrich_qualified_opportunities(
        [opportunity],
        client=client,
        settings=Settings(per_domain_delay_seconds=0),
        seed_path=seeds,
        store=MemoryLeadStore(),
        deadline_monotonic=10.0,
        monotonic_fn=lambda: 11.0,
        sleep_fn=lambda _: None,
    )
    assert mapping == {}
    assert client.calls == 0
