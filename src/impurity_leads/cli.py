import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from impurity_leads.adapters.clinical_trials import ClinicalTrialsAdapter
from impurity_leads.adapters.company_site import CompanySiteAdapter
from impurity_leads.adapters.common_crawl import CommonCrawlAdapter
from impurity_leads.adapters.fda import FDAAdapter
from impurity_leads.config import Settings, load_settings
from impurity_leads.contacts.discovery import contact_candidate_urls
from impurity_leads.contacts.models import RankedContact
from impurity_leads.contacts.pipeline import enrich_opportunity_contacts
from impurity_leads.crawling.fetch import HttpFetcher
from impurity_leads.crawling.robots import RobotsPolicy
from impurity_leads.crawling.sitemap import extract_sitemap_urls
from impurity_leads.export import export_csv, export_xlsx
from impurity_leads.models import Opportunity, SourceRecord
from impurity_leads.pipeline import process_records
from impurity_leads.normalize import normalize_company_name
from impurity_leads.seeds import load_company_seeds, relevant_candidate_urls
from impurity_leads.storage.memory import MemoryLeadStore


def seconds_remaining(start_monotonic: float, now_monotonic: float, deadline_minutes: int) -> float:
    return max(0.0, deadline_minutes * 60.0 - (now_monotonic - start_monotonic))


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def fixture_smoke_records() -> list[SourceRecord]:
    root = _project_root()
    fda_payload = json.loads((root / "tests/fixtures/fda_record.json").read_text())
    records = FDAAdapter().parse(fda_payload)

    site = CompanySiteAdapter()
    job_html = (root / "tests/fixtures/company_job.html").read_text()
    tender_html = (root / "tests/fixtures/tender_rfq.html").read_text()
    records.extend(site.parse_html("https://example.com/jobs/1", job_html, "Example Pharma", ["Drug X"]))
    records.extend(site.parse_html("https://example.com/tender/1", tender_html, "Example Pharma", ["Drug X"]))
    return records


def _structured_headers(settings: Settings) -> dict[str, str]:
    identity = settings.user_agent.strip() or "SVAK-Impurity-Lead-Research/0.1"
    user_agent = identity if identity.lower().startswith("mozilla/") else f"Mozilla/5.0 (compatible; {identity})"
    return {"User-Agent": user_agent, "Accept": "application/json"}


def _log_source_http_error(source: str, error: Exception) -> None:
    response = getattr(error, "response", None)
    status = getattr(response, "status_code", None)
    if status is not None:
        print(f"{source}=skipped status={status}")
    else:
        print(f"{source}=skipped error={error.__class__.__name__}")


def fetch_structured_records(client, settings: Settings | None = None) -> list[SourceRecord]:
    settings = settings or Settings()
    headers = _structured_headers(settings)
    records: list[SourceRecord] = []

    try:
        trials_response = client.get(
            "https://clinicaltrials.gov/api/v2/studies",
            params={
                "query.term": "AREA[Phase]PHASE3 AND AREA[InterventionType]DRUG",
                "pageSize": 100,
                "format": "json",
            },
            headers=headers,
        )
        trials_response.raise_for_status()
        trials_payload = trials_response.json()
        trial_adapter = ClinicalTrialsAdapter()
        for study in trials_payload.get("studies", []):
            records.extend(trial_adapter.parse(study))
    except Exception as error:
        _log_source_http_error("clinical_trials", error)

    try:
        fda_response = client.get(
            "https://api.fda.gov/drug/drugsfda.json",
            params={"limit": 99},
            headers=headers,
        )
        fda_response.raise_for_status()
        fda_payload = fda_response.json()
        fda_adapter = FDAAdapter()
        for result in fda_payload.get("results", []):
            records.extend(fda_adapter.parse(result))
    except Exception as error:
        _log_source_http_error("fda", error)

    return records


def fetch_seeded_company_records(
    client,
    seed_path: str | Path,
    settings: Settings,
    sleep_fn=time.sleep,
    deadline_monotonic: float | None = None,
    monotonic_fn=time.monotonic,
) -> list[SourceRecord]:
    seed_path = Path(seed_path)
    if not seed_path.exists():
        return []

    records: list[SourceRecord] = []
    site_adapter = CompanySiteAdapter()
    for seed in load_company_seeds(seed_path):
        if deadline_monotonic is not None and monotonic_fn() >= deadline_monotonic:
            break
        try:
            base_url = f"https://{seed.domain}"
            robots_policy = RobotsPolicy.fetch(client, base_url, settings.user_agent)
            if robots_policy.disallow_all:
                continue
            fetcher = HttpFetcher(
                client=client,
                robots_policy=robots_policy,
                user_agent=settings.user_agent,
                max_retries=settings.max_retries,
                sleep_fn=sleep_fn,
            )

            sitemap_urls: list[str] = []
            sitemap_xml = fetcher.fetch(f"{base_url}/sitemap.xml")
            if sitemap_xml:
                try:
                    sitemap_urls = extract_sitemap_urls(sitemap_xml)
                except (ValueError, TypeError):
                    sitemap_urls = []
                except Exception:
                    sitemap_urls = []

            common_urls: list[str] = []
            try:
                common_urls = CommonCrawlAdapter(
                    client=client,
                    user_agent=settings.user_agent,
                    max_urls_per_domain=10,
                    sleep_fn=sleep_fn,
                ).discover(seed.domain)
            except Exception:
                common_urls = []

            for url in relevant_candidate_urls(seed.domain, sitemap_urls, common_urls, cap=15):
                if deadline_monotonic is not None and monotonic_fn() >= deadline_monotonic:
                    break
                html = fetcher.fetch(url)
                if not html:
                    continue
                records.extend(
                    site_adapter.parse_html(
                        url=url,
                        html=html,
                        company_name=seed.company_name,
                        molecule_candidates=seed.molecules,
                    )
                )
                if settings.per_domain_delay_seconds > 0:
                    sleep_fn(settings.per_domain_delay_seconds)
        except Exception as error:
            _log_source_http_error(f"company={seed.domain}", error)
            continue
    return records


def collect_daily_records(
    client,
    settings: Settings,
    seed_path: str | Path,
    sleep_fn=time.sleep,
    deadline_monotonic: float | None = None,
    monotonic_fn=time.monotonic,
) -> list[SourceRecord]:
    records = fetch_structured_records(client, settings)
    records.extend(
        fetch_seeded_company_records(
            client,
            seed_path=seed_path,
            settings=settings,
            sleep_fn=sleep_fn,
            deadline_monotonic=deadline_monotonic,
            monotonic_fn=monotonic_fn,
        )
    )
    return records


def select_contact_enrichment_targets(
    opportunities: list[Opportunity],
    limit: int = 30,
) -> list[Opportunity]:
    qualified = [item for item in opportunities if item.priority in {"HOT", "HIGH"}]
    qualified.sort(key=lambda item: item.score, reverse=True)
    return qualified[: max(0, limit)]


def enrich_qualified_opportunities(
    opportunities: list[Opportunity],
    *,
    client,
    settings: Settings,
    seed_path: str | Path,
    store,
    sleep_fn=time.sleep,
    deadline_monotonic: float | None = None,
    monotonic_fn=time.monotonic,
) -> dict[tuple[str, str], list[RankedContact]]:
    seed_path = Path(seed_path)
    if not seed_path.exists():
        return {}
    seeds = {normalize_company_name(seed.company_name): seed for seed in load_company_seeds(seed_path)}
    contact_map: dict[tuple[str, str], list[RankedContact]] = {}
    contact_terms = (
        "leadership", "management", "team", "people", "about", "research", "science",
        "rd", "r-and-d", "analytical", "development", "quality", "regulatory",
        "procurement", "sourcing", "contact", "press", "news", "investor",
    )
    for opportunity in select_contact_enrichment_targets(opportunities, limit=30):
        if deadline_monotonic is not None and monotonic_fn() >= deadline_monotonic:
            break
        seed = seeds.get(normalize_company_name(opportunity.company_name))
        if seed is None:
            continue
        try:
            base_url = f"https://{seed.domain}"
            robots_policy = RobotsPolicy.fetch(client, base_url, settings.user_agent)
            if robots_policy.disallow_all:
                continue
            fetcher = HttpFetcher(
                client=client,
                robots_policy=robots_policy,
                user_agent=settings.user_agent,
                max_retries=settings.max_retries,
                sleep_fn=sleep_fn,
            )

            sitemap_urls: list[str] = []
            sitemap_xml = fetcher.fetch(f"{base_url}/sitemap.xml")
            if sitemap_xml:
                try:
                    sitemap_urls = extract_sitemap_urls(sitemap_xml)
                except Exception:
                    sitemap_urls = []

            common_urls: list[str] = []
            if deadline_monotonic is None or monotonic_fn() < deadline_monotonic:
                try:
                    common_urls = CommonCrawlAdapter(
                        client=client,
                        user_agent=settings.user_agent,
                        max_urls_per_domain=12,
                        sleep_fn=sleep_fn,
                    ).discover(seed.domain, url_terms=contact_terms)
                except Exception:
                    common_urls = []

            page_documents: list[tuple[str, str]] = []
            for url in contact_candidate_urls([*sitemap_urls, *common_urls], seed.domain, limit=12):
                if deadline_monotonic is not None and monotonic_fn() >= deadline_monotonic:
                    break
                html = fetcher.fetch(url)
                if not html:
                    continue
                page_documents.append((url, html))
                if settings.per_domain_delay_seconds > 0:
                    sleep_fn(settings.per_domain_delay_seconds)

            ranked = enrich_opportunity_contacts(
                opportunity,
                seed.domain,
                page_documents,
            )
            if not ranked:
                continue
            key = (opportunity.company_name, opportunity.molecule_name)
            contact_map[key] = ranked
            for contact in ranked:
                store.save_contact(opportunity.company_name, contact)
                store.link_opportunity_contact(opportunity, contact)
        except Exception as error:
            _log_source_http_error(f"contacts={seed.domain}", error)
            continue
    return contact_map


def _export(opportunities, directory: Path, stem: str, contacts_by_opportunity=None) -> tuple[Path, Path]:
    directory.mkdir(parents=True, exist_ok=True)
    return (
        export_csv(opportunities, directory / f"{stem}.csv", contacts_by_opportunity),
        export_xlsx(opportunities, directory / f"{stem}.xlsx", contacts_by_opportunity),
    )


def run_export(input_path: str | Path, output_dir: str | Path) -> int:
    payload = json.loads(Path(input_path).read_text(encoding="utf-8"))
    opportunities = [Opportunity.model_validate(item) for item in payload]
    csv_path, xlsx_path = _export(opportunities, Path(output_dir), "opportunities")
    print(f"csv={csv_path}")
    print(f"xlsx={xlsx_path}")
    return 0


def run_fixture_smoke() -> int:
    store = MemoryLeadStore()
    opportunities = process_records(fixture_smoke_records(), store)
    csv_path, xlsx_path = _export(opportunities, _project_root() / "exports", "fixture-opportunities")
    print(f"signals={len(store.signals)} opportunities={len(opportunities)}")
    for opportunity in opportunities:
        print(f"{opportunity.priority}\t{opportunity.score}\t{opportunity.company_name}\t{opportunity.molecule_name}")
    print(f"csv={csv_path}")
    print(f"xlsx={xlsx_path}")
    return 0 if opportunities else 1


def run_daily(workers: int | None = None, fresh: bool = False) -> int:
    from impurity_leads.execution.daily import run_daily as execute_daily
    settings = load_settings()
    return execute_daily(settings, _project_root(), workers=workers or settings.workers, fresh=fresh)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Impurity synthesis lead intelligence engine")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("test-fixtures", help="run the fixture-only end-to-end smoke test")
    export_parser = subparsers.add_parser("export", help="export opportunity JSON to CSV and Excel")
    export_parser.add_argument("input", help="JSON file containing a list of opportunities")
    export_parser.add_argument("--output-dir", default="exports", help="directory for CSV/XLSX output")
    daily_parser = subparsers.add_parser("run-daily", help="resume or start a durable daily crawl")
    daily_parser.add_argument("--workers", type=int, choices=range(1, 33), default=None, metavar="1-32")
    daily_parser.add_argument("--fresh", action="store_true", help="start a new run without deleting history")
    subparsers.add_parser("status", help="show latest durable run (read-only)")
    export_run_parser = subparsers.add_parser("export-run", help="regenerate exports from a completed durable run")
    export_run_parser.add_argument("run_id", nargs="?", default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "test-fixtures":
        return run_fixture_smoke()
    if args.command == "export":
        return run_export(args.input, args.output_dir)
    if args.command == "run-daily":
        return run_daily(workers=args.workers, fresh=args.fresh)
    if args.command == "status":
        from impurity_leads.execution.daily import status
        return status(load_settings())
    if args.command == "export-run":
        from impurity_leads.execution.daily import export_run
        return export_run(load_settings(), _project_root(), args.run_id)
    raise AssertionError(f"Unhandled command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
