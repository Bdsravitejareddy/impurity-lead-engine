import json
import socket
import ssl
from pathlib import Path

import httpx
import pytest

from impurity_leads import cli
from impurity_leads.adapters.common_crawl import CommonCrawlAdapter
from impurity_leads.config import Settings
from impurity_leads.crawling.fetch import HttpFetcher


ERRORS = [socket.gaierror("DNS failed"), ssl.SSLError("TLS failed"),
          httpx.ConnectError("TLS failed"), httpx.ReadTimeout("timed out")]


def seeds_file(tmp_path):
    path = tmp_path / "companies.csv"
    path.write_text("company_name,domain,molecules\nBroken,broken.example,Drug X\nExample Pharma,example.com,Drug X\n")
    return path


def company_response(request):
    if request.url.path == "/robots.txt":
        return httpx.Response(404)
    if request.url.path == "/sitemap.xml":
        return httpx.Response(200, text='<urlset><url><loc>https://example.com/jobs/1</loc></url></urlset>')
    if request.url.path == "/jobs/1":
        return httpx.Response(200, text=Path("tests/fixtures/company_job.html").read_text())
    return httpx.Response(404)


@pytest.mark.parametrize("error", ERRORS)
@pytest.mark.parametrize("stage", ["/robots.txt", "/sitemap.xml", "/jobs/1"])
def test_company_network_failure_keeps_next_company(tmp_path, error, stage):
    calls = []
    def handler(request):
        calls.append(str(request.url))
        if request.url.host == "broken.example":
            if request.url.path == stage:
                raise error
            if request.url.path == "/sitemap.xml":
                return httpx.Response(200, text='<urlset><url><loc>https://broken.example/jobs/1</loc></url></urlset>')
        return company_response(request)
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        records = cli.fetch_seeded_company_records(client, seeds_file(tmp_path),
            Settings(max_retries=0, per_domain_delay_seconds=0), sleep_fn=lambda _: None)
    assert any(r.company_name_raw == "Example Pharma" for r in records)
    assert f"https://broken.example{stage}" in calls
    assert all(url.startswith("https://") for url in calls)


@pytest.mark.parametrize("status, allowed", [(404, True), (403, False), (401, False), (503, False), (429, False)])
def test_robots_status_controls_company_crawl(tmp_path, status, allowed):
    calls = []
    def handler(request):
        calls.append(str(request.url))
        if request.url.path == "/robots.txt":
            return httpx.Response(status, text="an error page")
        return company_response(request)
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        records = cli.fetch_seeded_company_records(client, seeds_file(tmp_path),
            Settings(max_retries=0, per_domain_delay_seconds=0), sleep_fn=lambda _: None)
    assert bool(records) is allowed
    if not allowed:
        assert all(url.endswith("/robots.txt") for url in calls)


@pytest.mark.parametrize("error", ERRORS + [ValueError("invalid JSON")])
@pytest.mark.parametrize("failed_host", ["clinicaltrials.gov", "api.fda.gov"])
def test_failed_structured_source_keeps_other_source(error, failed_host):
    def handler(request):
        if request.url.host == failed_host:
            raise error
        fixture = "clinical_trials_study.json" if request.url.host == "clinicaltrials.gov" else "fda_record.json"
        payload = json.loads((Path("tests/fixtures") / fixture).read_text())
        return httpx.Response(200, json={"studies" if request.url.host == "clinicaltrials.gov" else "results": [payload]})
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        records = cli.fetch_structured_records(client)
    assert records
    assert all(failed_host not in r.source_url for r in records)


@pytest.mark.parametrize("factory", [HttpFetcher, CommonCrawlAdapter])
def test_owned_crawler_clients_ignore_environment_cert_settings(monkeypatch, factory):
    monkeypatch.setenv("SSL_CERT_FILE", "/nonexistent/crawler-test.pem")
    component = factory()
    component.client.close()


def test_daily_client_ignores_environment_cert_settings(monkeypatch, tmp_path):
    # Live daily now requires Supabase; exercise its network client directly.
    from impurity_leads.execution.http import CrawlClient, HostGate

    monkeypatch.setenv("SSL_CERT_FILE", "/nonexistent/crawler-test.pem")
    with CrawlClient(None, Settings(), HostGate()) as client:
        assert client.client is not None


def test_owned_client_blocks_https_to_http_redirect_before_request(monkeypatch):
    calls = []
    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(302, headers={"Location": "http://example.com/plain"})
    original = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kw: original(transport=httpx.MockTransport(handler), **kw))
    fetcher = HttpFetcher(max_retries=0)
    try:
        assert fetcher.fetch("https://example.com/secure") is None
    finally:
        fetcher.client.close()
    assert calls == ["https://example.com/secure"]


def test_daily_collection_survives_all_external_sources_failing(tmp_path):
    def handler(request):
        if request.url.host in {"clinicaltrials.gov", "api.fda.gov", "index.commoncrawl.org"}:
            raise httpx.ConnectError("source unavailable")
        return company_response(request)
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        records = cli.collect_daily_records(client, Settings(max_retries=0, per_domain_delay_seconds=0),
            seeds_file(tmp_path), sleep_fn=lambda _: None)
    assert any(r.company_name_raw == "Example Pharma" for r in records)


def test_owned_client_follows_https_redirect_to_missing_robots(monkeypatch):
    from impurity_leads.crawling.robots import RobotsPolicy

    def handler(request):
        if request.url.host == "example.com":
            return httpx.Response(301, headers={"Location": "https://www.example.com/robots.txt"})
        return httpx.Response(404)
    original = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kw: original(transport=httpx.MockTransport(handler), **kw))
    fetcher = HttpFetcher()
    try:
        policy = RobotsPolicy.fetch(fetcher.client, "https://example.com", "crawler")
        assert policy.can_fetch("https://example.com/jobs/1")
    finally:
        fetcher.client.close()


@pytest.mark.parametrize("error", ERRORS)
def test_contact_enrichment_keeps_next_company_after_network_failure(tmp_path, error):
    from impurity_leads.models import Opportunity
    from impurity_leads.storage.memory import MemoryLeadStore

    def handler(request):
        if request.url.host == "broken.example":
            raise error
        if request.url.path == "/sitemap.xml":
            return httpx.Response(200, text='<urlset><url><loc>https://example.com/leadership</loc></url></urlset>')
        if request.url.path == "/leadership":
            return httpx.Response(200, text=Path("tests/fixtures/contact_leadership.html").read_text())
        return httpx.Response(404)
    opportunities = [Opportunity(company_name=name, molecule_name="Drug X", score=90,
        priority="HOT", likely_need_type=["nitrosamine/NDSRI"], rationale="test")
        for name in ["Broken", "Example Pharma"]]
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        contacts = cli.enrich_qualified_opportunities(opportunities, client=client,
            settings=Settings(max_retries=0, per_domain_delay_seconds=0),
            seed_path=seeds_file(tmp_path), store=MemoryLeadStore(), sleep_fn=lambda _: None)
    assert contacts[("Example Pharma", "Drug X")]
    assert ("Broken", "Drug X") not in contacts
