#!/usr/bin/env python
"""Run the bounded, read-only enrichment feasibility spike.

Input is a JSON array of candidate rows exported by a read-only query. No
Supabase client is created and no production data is written.
"""
import argparse
import json
import sys
import time
from pathlib import Path
from urllib.parse import quote_plus

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from impurity_leads.adapters.common_crawl import CommonCrawlAdapter
from impurity_leads.adapters.company_site import CompanySiteAdapter
from impurity_leads.adapters.fda import FDAAdapter
from impurity_leads.crawling.client import create_crawl_client
from impurity_leads.crawling.robots import RobotsPolicy
from impurity_leads.enrichment_spike import run_spike, select_candidates
from impurity_leads.models import SourceRecord


TERMS = ("impurity", "degradation", "nitrosamine", "ndsri", "genotoxic", "stability", "analytical", "validation")


def enrich_candidate(candidate, max_pages, deadline):
    settings_timeout = httpx.Timeout(20.0, connect=5.0)
    source_status = {
        "company_site": {"attempted": False, "status": "not_configured", "records": 0},
        "europe_pmc": {"attempted": False, "status": "not_configured", "records": 0},
        "fda": {"attempted": False, "status": "not_configured", "records": 0},
        "regulatory": {"attempted": False, "status": "not_configured", "records": 0},
    }
    enrich_candidate.last_source_status = source_status
    with create_crawl_client(timeout=settings_timeout) as client:
        policy = None
        urls = []
        if candidate.domain:
            try:
                source_status["company_site"]["attempted"] = True
                policy = RobotsPolicy.fetch(client, f"https://{candidate.domain}", "SVAK-Impurity-Lead-Research/0.1")
                if not policy.disallow_all:
                    urls = [f"https://{candidate.domain}/"]
                    urls.extend(CommonCrawlAdapter(client=client, max_urls_per_domain=max_pages, sleep_fn=lambda _: None).discover(candidate.domain, url_terms=TERMS))
                else:
                    source_status["company_site"].update(status="failed", error="robots_blocked")
            except Exception:
                source_status["company_site"].update(status="failed", error="transport")
        else:
            source_status["company_site"].update(status="no_match")
        seen = set()
        adapter = CompanySiteAdapter()
        for url in urls:
            if len(seen) >= max_pages or time.monotonic() >= deadline:
                break
            if url in seen or not policy.can_fetch(url):
                continue
            seen.add(url)
            try:
                response = client.get(url)
                if response.status_code != 200:
                    continue
                records = adapter.parse_html(url, response.text, candidate.company_name, [candidate.molecule])
                source_status["company_site"]["records"] += len(records)
            except Exception:
                records = []
            for record in records:
                yield record, 1
        if source_status["company_site"]["attempted"] and source_status["company_site"]["status"] == "not_configured":
            source_status["company_site"]["status"] = "records" if source_status["company_site"]["records"] else "no_match"

        if len(seen) < max_pages and time.monotonic() < deadline:
            source_status["europe_pmc"]["attempted"] = True
            query = f'"{candidate.molecule}" AND ({" OR ".join(TERMS)})'
            try:
                response = client.get("https://www.ebi.ac.uk/europepmc/webservices/rest/search",
                                      params={"query": query, "format": "json", "pageSize": 5})
                if response.status_code == 200:
                    for item in response.json().get("resultList", {}).get("result", []):
                        text = " ".join(str(item.get(key) or "") for key in ("title", "abstractText"))
                        if candidate.company_name.casefold() in text.casefold():
                            identifier = item.get("pmid") or item.get("doi") or item.get("id")
                            url = f"https://europepmc.org/article/MED/{identifier}" if identifier else "https://europepmc.org/"
                            yield SourceRecord(source_name="europe_pmc", source_type="publication", source_record_id=str(identifier) if identifier else None,
                                               source_url=url, fetched_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
                                               company_name_raw=candidate.company_name, molecule_name_raw=candidate.molecule,
                                               signal_text=text), 1
                            source_status["europe_pmc"]["records"] += 1
                source_status["europe_pmc"]["status"] = "records" if source_status["europe_pmc"]["records"] else "no_match"
            except Exception:
                source_status["europe_pmc"].update(status="failed", error="transport")

        if len(seen) < max_pages and time.monotonic() < deadline:
            source_status["fda"]["attempted"] = True
            try:
                response = client.get("https://api.fda.gov/drug/drugsfda.json", params={"limit": 20, "search": f'products.active_ingredients.name:"{quote_plus(candidate.molecule)}"'})
                if response.status_code == 200:
                    for payload in response.json().get("results", []):
                        records = FDAAdapter().parse(payload)
                        for record in records:
                            if record.company_name_raw and candidate.company_name.casefold() in record.company_name_raw.casefold() and candidate.molecule.casefold() in (record.molecule_name_raw or "").casefold():
                                yield record, 1
                                source_status["fda"]["records"] += 1
                source_status["fda"]["status"] = "records" if source_status["fda"]["records"] else "no_match"
            except Exception:
                source_status["fda"].update(status="failed", error="transport")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("candidates", type=Path)
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--max-pages", type=int, default=8)
    parser.add_argument("--budget-seconds", type=float, default=120.0)
    parser.add_argument("--select-only", action="store_true")
    parser.add_argument("--domain-overrides", type=Path)
    args = parser.parse_args()
    rows = json.loads(args.candidates.read_text(encoding="utf-8"))
    overrides = json.loads(args.domain_overrides.read_text(encoding="utf-8")) if args.domain_overrides else {}
    candidates = select_candidates(rows, limit=args.limit, domain_overrides=overrides)
    if args.select_only:
        print(json.dumps([candidate.selection_report() for candidate in candidates], indent=2))
        return
    report = run_spike(candidates, enrich_candidate, max_pages=args.max_pages, budget_seconds=args.budget_seconds)
    print(json.dumps(report, indent=2, default=str))


if __name__ == "__main__":
    main()
