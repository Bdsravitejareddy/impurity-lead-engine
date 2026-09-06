"""Small, read-only enrichment feasibility spike.

This module deliberately keeps candidate state in memory and reuses the normal
SourceRecord/classifier/scoring pipeline. It is not the durable watchlist.
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone
import time
from typing import Callable, Iterable

from impurity_leads.classify import looks_like_impurity_vendor
from impurity_leads.models import SourceRecord
from impurity_leads.normalize import normalize_company_name, normalize_molecule_name
from impurity_leads.pipeline import process_records
from impurity_leads.score import score_signals
from impurity_leads.storage.memory import MemoryLeadStore


TECHNICAL_TERMS = ("impurity", "degradation", "nitrosamine", "ndsri", "genotoxic",
                   "stability", "analytical", "validation")


@dataclass
class Candidate:
    company_id: str
    molecule_id: str
    company_name: str
    molecule: str
    domain: str
    initial_score: int
    initial_records: list[SourceRecord] = field(default_factory=list)
    latest_event: str | None = None
    stored_domain: str = ""
    domain_override: str | None = None
    source_url: str | None = None
    source_record_id: str | None = None

    def selection_report(self) -> dict:
        return {
            "company": self.company_name,
            "molecule": self.molecule,
            "initial_score": self.initial_score,
            "latest_regulatory_event": self.latest_event,
            "current_stored_domain": self.stored_domain,
            "source_url": self.source_url,
            "source_record_id": self.source_record_id,
            "company_site_search_available": _usable_domain(self.domain),
            "publication_patent_regulatory_can_proceed_without_domain": True,
        }


def _latest(value):
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            pass
    return datetime.min.replace(tzinfo=timezone.utc)


def _usable_domain(value: str | None) -> bool:
    if not isinstance(value, str):
        return False
    domain = value.strip().lower().removeprefix("https://").removeprefix("http://").split("/", 1)[0]
    return bool(domain and "." in domain and " " not in domain and all(part for part in domain.split(".")))


def select_candidates(rows: Iterable[dict], limit: int = 5, domain_overrides: dict[str, str] | None = None) -> list[Candidate]:
    domain_overrides = domain_overrides or {}
    eligible = []
    for row in rows:
        types = {str(item) for item in (row.get("signal_types") or [])}
        score = row.get("score")
        if (not row.get("company_id") or not row.get("molecule_id") or
                not row.get("company") or not row.get("molecule") or
                row.get("excluded") or types != {"regulatory_application"} or not isinstance(score, (int, float)) or
                not 20 <= score <= 24 or row.get("has_opportunity")):
            continue
        stored_domain = str(row.get("domain") or "").strip().lower().removeprefix("www.")
        override = domain_overrides.get(str(row["company"]))
        domain = str(override or stored_domain).strip().lower().removeprefix("www.")
        eligible.append(Candidate(str(row["company_id"]), str(row["molecule_id"]),
                                  str(row["company"]), str(row["molecule"]),
                                  domain, int(score), list(row.get("initial_records") or []), row.get("latest_event"),
                                  stored_domain=stored_domain, domain_override=override,
                                  source_url=row.get("source_url"), source_record_id=row.get("source_record_id")))
    eligible.sort(key=lambda c: (-c.initial_score, -_latest(c.latest_event).timestamp(), c.company_id, c.molecule_id))
    return eligible[:max(0, limit)]


def accept_evidence(candidate: Candidate, record: SourceRecord) -> bool:
    company = normalize_company_name(record.company_name_raw or "")
    molecule = normalize_molecule_name(record.molecule_name_raw or record.active_ingredient_raw or "")
    if company != normalize_company_name(candidate.company_name) or molecule != normalize_molecule_name(candidate.molecule):
        return False
    if record.metadata_json.get("is_impurity_vendor") or looks_like_impurity_vendor(record.signal_text):
        return False
    text = record.signal_text.casefold()
    return normalize_molecule_name(candidate.molecule) in text and any(term in text for term in TECHNICAL_TERMS)


def _baseline(candidate: Candidate) -> list[SourceRecord]:
    if candidate.initial_records:
        return candidate.initial_records
    return [SourceRecord(source_name="production", source_type="regulatory",
                         source_record_id=f"spike:{candidate.company_id}:{candidate.molecule_id}",
                         source_url="https://api.fda.gov/drug/drugsfda.json",
                         fetched_at=datetime.now(timezone.utc), company_name_raw=candidate.company_name,
                         molecule_name_raw=candidate.molecule, signal_text=f"{candidate.molecule} FDA application activity",
                         metadata_json={"application_number": "spike-baseline"})]


def run_spike(candidates: list[Candidate], enrich: Callable[[Candidate, int, float], Iterable[tuple[SourceRecord, int]]], *,
              max_pages: int = 8, budget_seconds: float = 120.0, clock: Callable[[], float] = time.monotonic) -> dict:
    report = {"selected": [c.__dict__ | {"initial_records": None} for c in candidates], "investigated": [], "promoted": [], "exhausted": []}
    for candidate in candidates:
        started = clock(); deadline = started + budget_seconds
        found, rejected, urls, pages = [], [], [], 0
        try:
            for record, _ in enrich(candidate, max_pages, deadline):
                if pages >= max_pages or clock() >= deadline:
                    break
                pages += 1
                urls.append(record.source_url)
                (found if accept_evidence(candidate, record) else rejected).append(record)
        except Exception as error:
            rejected.append({"source_url": "", "reason": error.__class__.__name__})
        accepted_records = _baseline(candidate) + found
        store = MemoryLeadStore()
        opportunities = process_records(accepted_records, store)
        match = next((o for o in opportunities if normalize_company_name(o.company_name) == normalize_company_name(candidate.company_name)
                      and normalize_molecule_name(o.molecule_name) == normalize_molecule_name(candidate.molecule)), None)
        final_score = match.score if match else score_signals([s for s in store.signals if s.signal_type != "impurity_vendor_exclusion"])
        item = {"company": candidate.company_name, "molecule": candidate.molecule, "initial_score": candidate.initial_score,
                "evidence_found": [r.signal_text for r in found], "accepted_signal_types": [s.signal_type for s in store.signals if s.signal_type != "regulatory_application"],
                "rejected": [{"url": getattr(r, "source_url", ""), "reason": "linkage_or_term_check"} for r in rejected if isinstance(r, SourceRecord)],
                "source_urls": urls, "pages": pages, "requests": pages, "elapsed_seconds": max(0.0, clock() - started),
                "final_score": final_score, "priority": match.priority if match else None}
        report["investigated"].append(item)
        if match and match.score >= 50:
            report["promoted"].append(item)
            break
        report["exhausted"].append(item)
    return report
