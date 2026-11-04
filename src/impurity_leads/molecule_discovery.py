"""Molecule-first discovery of people with dated impurity/analytical work.

For each HOT/HIGH opportunity this finds people whose own public work ties
them to the opportunity's molecule *at the opportunity's company*:

1. Europe PMC papers on the molecule that discuss impurities, degradation
   products or stability-indicating methods, keeping only authors whose own
   affiliation names the company. The publication date is the source date.
2. ORCID public records (pub.orcid.org, no key) for those authors that carry
   an ORCID iD, read for dated employment at the company and a current title.
3. PatentsView inventors on process/impurity patents for the molecule that
   are assigned to the company (free key; skipped without one).

Every source written has a real ``source_date`` taken from the record itself
(publication, filing or ORCID modification date), never the crawl date, so
``score_contact`` dates the role from evidence instead of assuming it. Only
free public APIs are used; nothing is probed, scraped behind a login or paid.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Any, Callable
from urllib.parse import quote, urlencode, urlparse
from urllib.request import Request, urlopen

from impurity_leads.contacts.normalize import normalize_person_name, person_name_compatibility
from impurity_leads.normalize import clean_intervention_names, normalize_company_name
from impurity_leads.person_discovery import PersonCandidate, extract_authors, rank_candidate
from impurity_leads.research_discovery import EuropePmcProvider, SearchRequest
from impurity_leads.zero_cost import ProviderUsage, provider_for_url

SOURCE_KIND = "MOLECULE_DISCOVERY"
ORCID_API = "https://pub.orcid.org/v3.0"
PATENTSVIEW_API = "https://search.patentsview.org/api/v1/patent/"
LINKS_PER_OPPORTUNITY = 3
# Fallback tier: the company's own recent impurity/stability authors on any
# molecule, used only when molecule-specific work names too few people.
COMPANY_TIER_YEARS = 5
COMPANY_TIER_PAPERS = 5
COMPANY_TIER_PEOPLE = 5
_FORMER = re.compile(r"\b(?:formerly|former|previously|retired|emeritus)\b", re.I)
_BUYER_FUNCTIONS = ("analytical", "quality", "qc", "cmc", "stability", "regulatory", "chemical development",
                    "process", "pharmaceutical science", "pharmaceutical development", "api", "adl", "impurit")

# Phrases, not bare "degradation": that word alone matches protein- and
# DNA-degradation biology, whose authors do not buy reference standards.
IMPURITY_PHRASES = (
    "impurity", "impurities", "degradation product", "degradation products",
    "degradant", "degradants", "forced degradation", "stress degradation",
    "stability-indicating", "stability indicating", "related substances",
    "nitrosamine", "nitrosamines", "genotoxic",
)
PATENT_PROCESS_TERMS = ("process", "preparation", "impurit", "purification", "purity", "crystalline", "salt")
_SALT_WORDS = {
    "hydrochloride", "dihydrochloride", "hydrobromide", "fumarate", "maleate", "mesylate", "besylate",
    "tosylate", "tartrate", "succinate", "citrate", "sulfate", "sulphate", "acetate", "phosphate",
    "sodium", "potassium", "calcium", "magnesium", "monohydrate", "dihydrate", "hemihydrate",
    "trihydrate", "anhydrous", "hcl",
}
_GENERIC_COMPANY_WORDS = {
    "pharmaceuticals", "pharmaceutical", "pharma", "laboratories", "laboratory", "labs", "lifesciences",
    "life", "sciences", "science", "private", "pvt", "nyrt", "plc", "limited", "ltd", "inc", "co",
    "corp", "corporation", "company", "group", "holdings", "the", "and", "of", "gmbh", "ag", "sa",
    "kgaa", "industries", "healthcare", "therapeutics", "biosciences", "llc", "bv", "nv", "spa", "srl",
}
_EMAIL = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.I)


# ---------------------------------------------------------------------------
# Matching helpers


def _words(value: str) -> list[str]:
    text = re.sub(r"\([^)]*\)", " ", value or "")
    text = re.sub(r"['’`]s\b", "", text.casefold())
    text = re.sub(r"['’`]", "", text)
    return re.findall(r"[^\W_]+", text)


def company_tokens(company: str) -> list[str]:
    """Distinctive words of a company name ("Dr. Reddy's Laboratories" -> ["reddy"])."""
    words = [word for word in _words(normalize_company_name(company or "")) if word not in _GENERIC_COMPANY_WORDS]
    distinctive = [word for word in words if len(word) >= 3]
    return distinctive or words[:1]


def affiliation_matches(affiliation: str | None, company: str) -> bool:
    """True when every distinctive company word appears in the affiliation."""
    tokens = company_tokens(company)
    if not affiliation or not tokens:
        return False
    words = set(_words(affiliation))
    return all(token in words for token in tokens)


def molecule_names(name: str, synonyms: list[str] | tuple[str, ...] = ()) -> list[str]:
    """Base molecule names to search, salts stripped and combinations split."""
    names: list[str] = []
    for value in [name, *list(synonyms)[:3]]:
        for part in clean_intervention_names(str(value or "")) or [str(value or "")]:
            base = " ".join(word for word in part.split() if word.casefold() not in _SALT_WORDS).strip()
            if len(base) >= 4 and base.casefold() not in {existing.casefold() for existing in names}:
                names.append(base)
    return names[:4]


def _mentions(text: str, phrases: tuple[str, ...] | list[str]) -> list[str]:
    lower = text.casefold()
    return [phrase for phrase in phrases if re.search(rf"(?<!\w){re.escape(phrase.casefold())}", lower)]


def _parse_date(value: Any) -> str | None:
    text = str(value or "").strip()
    match = re.match(r"^(\d{4})(?:-(\d{2}))?(?:-(\d{2}))?", text)
    if not match:
        return None
    year, month, day = match.groups()
    return f"{year}-{month or '01'}-{day or '01'}"


# ---------------------------------------------------------------------------
# Data shapes


@dataclass(frozen=True)
class OpportunityTarget:
    opportunity_id: str
    company_id: str
    company_name: str
    molecule_name: str
    molecule_synonyms: tuple[str, ...] = ()
    priority: str = "HIGH"
    score: float = 0.0


@dataclass
class Evidence:
    """One dated, person-direct public record."""

    kind: str  # PUBLICATION | PATENT | ORCID_EMPLOYMENT
    url: str
    title: str
    source_date: str
    publisher: str
    source_type: str
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass
class Position:
    company_name: str
    title: str
    department: str | None
    start_date: str | None
    end_date: str | None
    date_precision: str


@dataclass
class DiscoveredPerson:
    name: str
    candidate: PersonCandidate
    department: str | None = None
    email: str | None = None
    orcid: str | None = None
    evidence: list[Evidence] = field(default_factory=list)
    positions: list[Position] = field(default_factory=list)
    title: str | None = None
    employment: str = "SOURCE_DATED_AFFILIATION"  # | ORCID_CURRENT | ORCID_ENDED

    @property
    def molecule_match(self) -> bool:
        return any(item.detail.get("molecule_match", True) for item in self.evidence if item.kind != "ORCID_EMPLOYMENT")

    @property
    def newest_date(self) -> str:
        return max(item.source_date for item in self.evidence)

    @property
    def identity_confidence(self) -> float:
        if self.employment == "ORCID_CURRENT":
            base = 0.86
        elif any(item.kind == "PUBLICATION" for item in self.evidence):
            base = 0.74
        else:
            base = 0.66  # patent inventor: assignee match, no personal affiliation
        if self.email:
            base += 0.04
        if len({item.kind for item in self.evidence}) >= 2:
            base += 0.04
        # An initial-only name ("Radich CL") is a weaker identity anchor.
        if len(normalize_person_name(self.name).split()[0]) <= 2:
            base -= 0.10
        return round(min(0.95, max(0.4, base)), 4)


# ---------------------------------------------------------------------------
# Politeness: one shared, throttled, budgeted JSON fetcher


FetchJson = Callable[[str, dict[str, str]], dict[str, Any]]


def http_get_json(url: str, headers: dict[str, str], timeout: float = 20.0) -> dict[str, Any]:
    request = Request(url, headers=headers)
    with urlopen(request, timeout=timeout) as response:  # noqa: S310 - fixed HTTPS API hosts
        return json.loads(response.read().decode("utf-8"))


class PoliteFetcher:
    """Per-host delay, a per-run request budget and provider accounting."""

    def __init__(self, fetch: FetchJson, *, user_agent: str, delay_seconds: float = 1.0,
                 max_requests: int = 120, usage: ProviderUsage | None = None,
                 sleep: Callable[[float], None] = time.sleep, clock: Callable[[], float] = time.monotonic):
        self.fetch = fetch
        self.user_agent = user_agent
        self.delay_seconds = delay_seconds
        self.max_requests = max_requests
        self.usage = usage
        self.sleep = sleep
        self.clock = clock
        self.requests = 0
        self._last: dict[str, float] = {}

    def __call__(self, url: str, headers: dict[str, str] | None = None) -> dict[str, Any]:
        if self.requests >= self.max_requests:
            raise RuntimeError("molecule_discovery_request_budget_exhausted")
        host = urlparse(url).hostname or ""
        last = self._last.get(host)
        if last is not None:
            wait = self.delay_seconds - (self.clock() - last)
            if wait > 0:
                self.sleep(wait)
        self.requests += 1
        if self.usage is not None:
            self.usage.record(provider_for_url(url), requests=1)
        try:
            return self.fetch(url, {"User-Agent": self.user_agent, "Accept": "application/json", **(headers or {})})
        finally:
            self._last[host] = self.clock()


# ---------------------------------------------------------------------------
# 1. Europe PMC


def europe_pmc_query(target: OpportunityTarget) -> str:
    names = " OR ".join(f'TITLE_ABS:"{name}"' for name in molecule_names(target.molecule_name, target.molecule_synonyms))
    terms = " OR ".join(f'TITLE_ABS:"{phrase}"' for phrase in IMPURITY_PHRASES)
    company = " AND ".join(f'AFF:"{token}"' for token in company_tokens(target.company_name))
    return f"({names}) AND ({terms}) AND {company}"


def europe_pmc_company_query(target: OpportunityTarget, *, today: str | None = None) -> str:
    year = int((today or datetime.now(timezone.utc).date().isoformat())[:4]) - COMPANY_TIER_YEARS
    terms = " OR ".join(f'TITLE_ABS:"{phrase}"' for phrase in IMPURITY_PHRASES)
    company = " AND ".join(f'AFF:"{token}"' for token in company_tokens(target.company_name))
    return f"({terms}) AND {company} AND FIRST_PDATE:[{year}-01-01 TO 3000-12-31]"


def _author_department(affiliation: str, company: str) -> str | None:
    """The affiliation segments before the company name, e.g. 'Analytical R&D'."""
    first = affiliation.split(" | ")[0]
    parts = [part.strip() for part in first.split(",")]
    kept: list[str] = []
    for part in parts:
        if affiliation_matches(part, company):
            break
        kept.append(part)
    department = ", ".join(kept).strip()
    return department[:200] if department and len(kept) < len(parts) else None


def _author_email(affiliation: str, name: str) -> str | None:
    """An address the paper prints for this author, if its local part names them."""
    surname = normalize_person_name(name).split()[-1:]
    for email in _EMAIL.findall(affiliation or ""):
        email = email.rstrip(".")
        local = re.sub(r"[^a-z]", "", email.split("@")[0].casefold())
        if surname and len(surname[0]) >= 3 and surname[0] in local:
            return email.casefold()
    return None


def _display_name(author: dict[str, Any], fallback: str) -> str:
    first, last = str(author.get("firstName") or "").strip(), str(author.get("lastName") or "").strip()
    if first and last and len(first.replace(".", "")) > 1:
        return f"{first} {last}"
    if last and author.get("initials"):
        initials = " ".join(f"{letter}." for letter in str(author["initials"]) if letter.isalpha())
        return f"{initials} {last}"
    return fallback


def publication_people(item: dict[str, Any], target: OpportunityTarget, *, require_molecule: bool = True) -> list[DiscoveredPerson]:
    """Authors of one Europe PMC record whose own affiliation names the company."""
    text = f"{item.get('title') or ''} {item.get('abstractText') or ''}"
    names = molecule_names(target.molecule_name, target.molecule_synonyms)
    impurity_terms = _mentions(text, IMPURITY_PHRASES)
    published = _parse_date(item.get("firstPublicationDate") or item.get("pubYear"))
    molecule_match = bool(_mentions(text, names))
    if not published or not impurity_terms or (require_molecule and not molecule_match):
        return []
    identifier = item.get("pmid") or item.get("id")
    source = "MED" if item.get("pmid") else str(item.get("source") or "MED")
    url = f"https://europepmc.org/article/{source}/{identifier}"
    raw_authors = (item.get("authorList") or {}).get("author") or []
    people: list[DiscoveredPerson] = []
    for candidate in extract_authors(item, technical_text=text):
        if not affiliation_matches(candidate.affiliation, target.company_name) or _FORMER.search(candidate.affiliation or ""):
            continue
        author = raw_authors[candidate.author_order - 1] if candidate.author_order - 1 < len(raw_authors) else {}
        name = _display_name(author, candidate.name)
        evidence = Evidence(
            kind="PUBLICATION", url=url, title=str(item.get("title") or "Publication")[:300],
            source_date=published, publisher="Europe PMC", source_type="Scientific publication",
            detail={
                "pmid": item.get("pmid"), "doi": item.get("doi"), "journal": (item.get("journalInfo") or {}).get("journal", {}).get("title"),
                "author_order": candidate.author_order, "author_count": len(raw_authors),
                "affiliation": (candidate.affiliation or "")[:1000], "impurity_terms": impurity_terms,
                "date_basis": "firstPublicationDate", "molecule_match": molecule_match,
            },
        )
        people.append(DiscoveredPerson(
            name=name, candidate=replace(candidate, name=name, source_date=published),
            department=_author_department(candidate.affiliation or "", target.company_name),
            email=_author_email(candidate.affiliation or "", name), orcid=candidate.orcid, evidence=[evidence],
        ))
    return people


def discover_publications(target: OpportunityTarget, fetch: PoliteFetcher, *, max_papers: int = 10, company_tier: bool = False,
                          today: str | None = None) -> list[DiscoveredPerson]:
    provider = EuropePmcProvider(lambda url: fetch(url))
    query = europe_pmc_company_query(target, today=today) if company_tier else europe_pmc_query(target)
    results = provider.discover(SearchRequest(query=query, seed_type="OPPORTUNITY", seed_id=target.opportunity_id,
                                              max_results=COMPANY_TIER_PAPERS if company_tier else max_papers))
    people: list[DiscoveredPerson] = []
    for result in results:
        people.extend(publication_people(result.metadata or {}, target, require_molecule=not company_tier))
    return people


# ---------------------------------------------------------------------------
# 2. ORCID


def _orcid_date(value: dict[str, Any] | None) -> tuple[str | None, str]:
    if not value:
        return None, "NONE"
    year = ((value.get("year") or {}).get("value"))
    month = ((value.get("month") or {}).get("value"))
    day = ((value.get("day") or {}).get("value"))
    if not year:
        return None, "NONE"
    precision = "DAY" if day else "MONTH" if month else "YEAR"
    return f"{year}-{month or '01'}-{day or '01'}", precision


def orcid_positions(payload: dict[str, Any], company: str) -> tuple[list[Position], str | None]:
    """Employments at the company and the record's last-modified date."""
    positions: list[Position] = []
    for group in payload.get("affiliation-group") or []:
        for summary in group.get("summaries") or []:
            row = summary.get("employment-summary") or {}
            organisation = str((row.get("organization") or {}).get("name") or "")
            if not affiliation_matches(organisation, company):
                continue
            start, start_precision = _orcid_date(row.get("start-date"))
            end, _ = _orcid_date(row.get("end-date"))
            positions.append(Position(
                company_name=organisation, title=str(row.get("role-title") or "").strip(),
                department=(str(row.get("department-name") or "").strip() or None),
                start_date=start, end_date=end, date_precision=start_precision,
            ))
    modified = (payload.get("last-modified-date") or {}).get("value")
    as_of = datetime.fromtimestamp(int(modified) / 1000, tz=timezone.utc).date().isoformat() if modified else None
    return positions, as_of


def confirm_with_orcid(person: DiscoveredPerson, target: OpportunityTarget, fetch: PoliteFetcher) -> DiscoveredPerson:
    if not person.orcid:
        return person
    orcid = person.orcid.rsplit("/", 1)[-1]
    payload = fetch(f"{ORCID_API}/{quote(orcid)}/employments")
    positions, as_of = orcid_positions(payload, target.company_name)
    if not positions:
        return person
    person.positions = positions
    current = [row for row in positions if not row.end_date]
    if current:
        newest = max(current, key=lambda row: row.start_date or "")
        person.employment = "ORCID_CURRENT"
        person.title = newest.title or None
        person.department = newest.department or person.department
    else:
        person.employment = "ORCID_ENDED"
    dated = as_of or max((row.end_date or row.start_date or "" for row in positions), default="")
    if dated:
        person.evidence.append(Evidence(
            kind="ORCID_EMPLOYMENT", url=f"https://orcid.org/{orcid}", title=f"ORCID employment record: {person.name}"[:300],
            source_date=dated, publisher="ORCID", source_type="ORCID record",
            detail={"orcid": orcid, "employment": person.employment, "date_basis": "last-modified-date" if as_of else "position dates",
                    "positions": [row.__dict__ for row in positions]},
        ))
    return person


# ---------------------------------------------------------------------------
# 3. PatentsView


def patentsview_url(target: OpportunityTarget, *, size: int = 10) -> str:
    names = molecule_names(target.molecule_name, target.molecule_synonyms)
    query = {"_and": [
        {"_or": [{"_text_phrase": {"patent_abstract": name}} for name in names] + [{"_text_phrase": {"patent_title": name}} for name in names]},
        {"_text_any": {"assignees.assignee_organization": " ".join(company_tokens(target.company_name))}},
    ]}
    fields = ["patent_id", "patent_title", "patent_abstract", "patent_date", "application.filing_date",
              "assignees.assignee_organization", "inventors.inventor_name_first", "inventors.inventor_name_last",
              "inventors.inventor_city", "inventors.inventor_country"]
    params = {"q": json.dumps(query, separators=(",", ":")), "f": json.dumps(fields, separators=(",", ":")),
              "o": json.dumps({"size": size}, separators=(",", ":")), "s": json.dumps([{"patent_date": "desc"}], separators=(",", ":"))}
    return f"{PATENTSVIEW_API}?{urlencode(params)}"


def patent_people(patent: dict[str, Any], target: OpportunityTarget) -> list[DiscoveredPerson]:
    assignees = [str(row.get("assignee_organization") or "") for row in patent.get("assignees") or []]
    if not any(affiliation_matches(name, target.company_name) for name in assignees):
        return []
    text = f"{patent.get('patent_title') or ''} {patent.get('patent_abstract') or ''}"
    if not _mentions(text, molecule_names(target.molecule_name, target.molecule_synonyms)):
        return []
    process_terms = [term for term in PATENT_PROCESS_TERMS if term in text.casefold()]
    if not process_terms:
        return []
    applications = patent.get("application") or []
    filed = _parse_date(applications[0].get("filing_date")) if applications else None
    source_date = filed or _parse_date(patent.get("patent_date"))
    if not source_date:
        return []
    patent_id = str(patent.get("patent_id") or "")
    evidence_detail = {"patent_id": patent_id, "assignees": assignees, "process_terms": process_terms,
                       "date_basis": "application.filing_date" if filed else "patent_date", "granted": patent.get("patent_date")}
    people: list[DiscoveredPerson] = []
    for order, inventor in enumerate(patent.get("inventors") or [], start=1):
        name = " ".join(filter(None, (str(inventor.get("inventor_name_first") or "").strip(), str(inventor.get("inventor_name_last") or "").strip())))
        if len(normalize_person_name(name).split()) < 2:
            continue
        candidate = PersonCandidate(name=name, given_name=inventor.get("inventor_name_first"), family_name=inventor.get("inventor_name_last"),
                                    affiliation=None, orcid=None, author_order=order, corresponding=False, source_date=source_date,
                                    technical_relevance=85.0 if "impurit" in text.casefold() else 70.0, state="TECHNICALLY_RELEVANT")
        people.append(DiscoveredPerson(name=name, candidate=candidate, evidence=[Evidence(
            kind="PATENT", url=f"https://patents.google.com/patent/US{patent_id}", title=str(patent.get("patent_title") or "Patent")[:300],
            source_date=source_date, publisher="USPTO PatentsView", source_type="Patent",
            detail={**evidence_detail, "inventor_order": order, "inventor_location": ", ".join(filter(None, (inventor.get("inventor_city"), inventor.get("inventor_country"))))},
        )]))
    return people


def discover_patents(target: OpportunityTarget, fetch: PoliteFetcher, api_key: str) -> list[DiscoveredPerson]:
    payload = fetch(patentsview_url(target), {"X-Api-Key": api_key})
    people: list[DiscoveredPerson] = []
    for patent in payload.get("patents") or []:
        people.extend(patent_people(patent, target))
    return people


# ---------------------------------------------------------------------------
# Orchestration


def merge_people(people: list[DiscoveredPerson]) -> list[DiscoveredPerson]:
    """Collapse the same person across papers/patents ("J Zheng" ~ "Jinjian Zheng")."""
    merged: list[DiscoveredPerson] = []
    for person in people:
        match = next((row for row in merged if person_name_compatibility(row.name, person.name) >= 0.8
                      or person_name_compatibility(person.name, row.name) >= 0.8
                      or (person.orcid and person.orcid == row.orcid)), None)
        if not match:
            merged.append(person)
            continue
        if len(normalize_person_name(person.name)) > len(normalize_person_name(match.name)):
            match.name, match.candidate = person.name, replace(person.candidate, name=person.name)
        known = {item.url for item in match.evidence}
        match.evidence.extend(item for item in person.evidence if item.url not in known)
        match.orcid = match.orcid or person.orcid
        match.email = match.email or person.email
        match.department = match.department or person.department
    return merged


def rank_people(people: list[DiscoveredPerson]) -> list[tuple[DiscoveredPerson, float]]:
    ranked = []
    for person in people:
        score = rank_candidate(person.candidate, company_match=True, current_role=person.employment == "ORCID_CURRENT")
        score += min(10, 3 * (len(person.evidence) - 1))
        if not person.molecule_match:
            score -= 15
        if any(term in str(person.department or person.title or "").casefold() for term in _BUYER_FUNCTIONS):
            score += 5
        ranked.append((person, round(min(100.0, score), 1)))
    ranked.sort(key=lambda pair: pair[0].newest_date, reverse=True)
    return sorted(ranked, key=lambda pair: (pair[0].employment == "ORCID_ENDED", -pair[1]))


def discover_for_opportunity(target: OpportunityTarget, fetch: PoliteFetcher, *, max_papers: int = 10,
                             patentsview_api_key: str | None = None, today: str | None = None) -> dict[str, Any]:
    """Run all providers for one opportunity; persistence is separate."""
    errors: dict[str, str] = {}
    people: list[DiscoveredPerson] = []
    try:
        people.extend(discover_publications(target, fetch, max_papers=max_papers))
    except Exception as exc:
        errors["europe_pmc"] = type(exc).__name__
    if patentsview_api_key:
        try:
            people.extend(discover_patents(target, fetch, patentsview_api_key))
        except Exception as exc:
            errors["patentsview"] = type(exc).__name__
    people = merge_people(people)
    if len(people) < LINKS_PER_OPPORTUNITY:
        try:
            people = merge_people(people + discover_publications(target, fetch, company_tier=True, today=today))
        except Exception as exc:
            errors["europe_pmc_company"] = type(exc).__name__
    # Cap the off-molecule tier before spending ORCID requests on it.
    off_molecule = {id(person) for person, _ in [pair for pair in rank_people(people) if not pair[0].molecule_match][:COMPANY_TIER_PEOPLE]}
    people = [person for person in people if person.molecule_match or id(person) in off_molecule]
    for person in people:
        try:
            confirm_with_orcid(person, target, fetch)
        except Exception as exc:
            errors["orcid"] = type(exc).__name__
    ranked = rank_people(people)
    return {"target": target, "people": ranked, "errors": errors}


# ---------------------------------------------------------------------------
# Persistence


def _stable_contact_id(company_id: str, normalized: str) -> str:
    from impurity_leads.storage.supabase_store import _stable_uuid
    return str(_stable_uuid("contact", f"{company_id}:{normalized}"))


def _data(response: Any) -> list[dict[str, Any]]:
    return list(getattr(response, "data", None) or [])


def _existing_contact(rows: list[dict[str, Any]], person: DiscoveredPerson) -> dict[str, Any] | None:
    normalized = normalize_person_name(person.name)
    for row in rows:
        if row.get("merged_into_contact_id"):
            continue
        name = str(row.get("display_name") or row.get("normalized_name") or "")
        if normalize_person_name(name) == normalized or person_name_compatibility(name, person.name) >= 0.92:
            return row
        # "J Zheng" on file and "Jinjian Zheng" now: reuse only with an
        # independent anchor, never on initials alone.
        if person_name_compatibility(person.name, name) >= 0.8 and person.email and str(row.get("primary_email") or "").casefold() == person.email:
            return row
    return None


def source_payload(contact_id: str, evidence: Evidence, target: OpportunityTarget) -> dict[str, Any]:
    return {
        "contact_id": contact_id,
        "url": evidence.url,
        "title": evidence.title,
        "publisher": evidence.publisher,
        "source_type": evidence.source_type,
        "source_date": evidence.source_date,
        "status": "USED",
        "evidence_strength": "HIGH" if evidence.kind in {"PUBLICATION", "ORCID_EMPLOYMENT"} else "MEDIUM",
        "why_used": {
            "PUBLICATION": "Named author whose own affiliation is the opportunity company, on impurity/stability work for the molecule.",
            "PATENT": "Named inventor on a company-assigned process/impurity patent for the molecule.",
            "ORCID_EMPLOYMENT": "Self-asserted, dated ORCID employment at the opportunity company.",
        }[evidence.kind],
        "source_kind": SOURCE_KIND,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "extraction_json": {**evidence.detail, "attribution": "PERSON_DIRECT", "evidence_kind": evidence.kind,
                            "molecule": target.molecule_name, "opportunity_id": target.opportunity_id},
    }


def persist_opportunity(client: Any, result: dict[str, Any]) -> dict[str, int]:
    """Write contacts, dated sources, works, ORCID positions and links."""
    target: OpportunityTarget = result["target"]
    metrics = {"people": 0, "new_contacts": 0, "existing_contacts": 0, "sources": 0, "works": 0, "positions": 0, "links": 0}
    company_contacts = _data(client.table("contacts").select("*").eq("company_id", target.company_id).execute())
    linked = 0
    for person, role_fit in result["people"]:
        metrics["people"] += 1
        existing = _existing_contact(company_contacts, person)
        now = datetime.now(timezone.utc).isoformat()
        if existing:
            contact_id = str(existing["id"])
            # Fill gaps only; operator-entered fields are never overwritten.
            patch = {key: value for key, value in {
                "title": person.title, "department": person.department, "primary_email": person.email,
            }.items() if value and not existing.get(key)}
            if person.email and patch.get("primary_email"):
                patch["email_status"] = "VERIFIED_PUBLIC"
            if person.identity_confidence > float(existing.get("contact_confidence") or 0):
                patch["contact_confidence"] = person.identity_confidence
            patch["last_seen_at"] = now
            client.table("contacts").update(patch).eq("id", contact_id).execute()
            existing.update(patch)
            metrics["existing_contacts"] += 1
        else:
            normalized = normalize_person_name(person.name)
            contact_id = _stable_contact_id(target.company_id, normalized)
            row = {
                "id": contact_id, "company_id": target.company_id, "normalized_name": normalized,
                "display_name": person.name, "title": person.title, "department": person.department,
                "primary_email": person.email, "email_status": "VERIFIED_PUBLIC" if person.email else "ROLE_ONLY",
                "role_fit_score": int(role_fit), "contact_confidence": person.identity_confidence,
                "first_seen_at": now, "last_seen_at": now,
            }
            client.table("contacts").insert(row).execute()
            company_contacts.append(row)
            metrics["new_contacts"] += 1
        source_ids: list[str] = []
        for evidence in person.evidence:
            response = client.table("contact_sources").upsert(source_payload(contact_id, evidence, target), on_conflict="contact_id,url").execute()
            rows = _data(response) or _data(client.table("contact_sources").select("id").eq("contact_id", contact_id).eq("url", evidence.url).limit(1).execute())
            source_id = str(rows[0]["id"]) if rows and rows[0].get("id") else None
            if source_id:
                source_ids.append(source_id)
            metrics["sources"] += 1
            if evidence.kind == "ORCID_EMPLOYMENT":
                continue
            work_type = evidence.kind
            if _data(client.table("contact_works").select("id").eq("contact_id", contact_id).eq("title", evidence.title).limit(1).execute()):
                continue
            client.table("contact_works").insert({
                "contact_id": contact_id, "work_type": work_type, "title": evidence.title, "work_date": evidence.source_date,
                "person_role": "Named author" if work_type == "PUBLICATION" else "Named inventor",
                "company_context": target.company_name, "topic": ", ".join(evidence.detail.get("impurity_terms") or evidence.detail.get("process_terms") or []),
                "molecules": [target.molecule_name] if evidence.detail.get("molecule_match", True) else [], "technical_themes": list(evidence.detail.get("impurity_terms") or evidence.detail.get("process_terms") or []),
                "attribution": "PERSON_DIRECT", "confidence": 0.82 if work_type == "PUBLICATION" else 0.72,
                "source_ids": [source_id] if source_id else [],
            }).execute()
            metrics["works"] += 1
        orcid_source = [sid for sid, item in zip(source_ids, person.evidence) if item.kind == "ORCID_EMPLOYMENT"]
        for position in person.positions:
            if not position.title:
                continue
            duplicate = _data(client.table("contact_positions").select("id").eq("contact_id", contact_id).eq("title", position.title).eq("start_date", position.start_date).limit(1).execute())
            if duplicate:
                continue
            client.table("contact_positions").insert({
                "contact_id": contact_id, "company_id": target.company_id, "company_name": position.company_name,
                "title": position.title, "department": position.department, "start_date": position.start_date,
                "end_date": position.end_date, "date_precision": position.date_precision, "attribution": "PERSON_DIRECT",
                "confidence": 0.85, "source_ids": orcid_source,
            }).execute()
            metrics["positions"] += 1
        # People ORCID shows as gone are kept as contacts but not offered as leads.
        if person.employment != "ORCID_ENDED" and linked < LINKS_PER_OPPORTUNITY and source_ids:
            linked += 1
            kinds = sorted({item.kind for item in person.evidence})
            client.table("opportunity_contacts").upsert({
                "opportunity_id": target.opportunity_id, "contact_id": contact_id, "role_fit_score": int(role_fit), "rank": linked,
                "rationale": f"{'/'.join(kinds)} on {target.molecule_name if person.molecule_match else 'impurity/stability work (other molecules)'} "
                             f"at {target.company_name}, newest {person.newest_date}; "
                             f"{'current employment confirmed by ORCID' if person.employment == 'ORCID_CURRENT' else 'employment dated by source, not confirmed current'}",
                "source_ids": source_ids,
            }, on_conflict="opportunity_id,contact_id").execute()
            metrics["links"] += 1
    return metrics


def load_targets(client: Any, *, limit: int) -> list[OpportunityTarget]:
    opportunities = _data(client.table("opportunities").select("id,company_id,molecule_id,priority,score,status")
                          .in_("priority", ["HOT", "HIGH"]).neq("status", "dismissed").order("score", desc=True).limit(limit).execute())
    targets: list[OpportunityTarget] = []
    for row in opportunities:
        company = _data(client.table("companies").select("id,legal_name,normalized_name").eq("id", row.get("company_id")).limit(1).execute())
        molecule = _data(client.table("molecules").select("id,canonical_name,synonyms").eq("id", row.get("molecule_id")).limit(1).execute())
        if not company or not molecule:
            continue
        targets.append(OpportunityTarget(
            opportunity_id=str(row["id"]), company_id=str(row["company_id"]),
            company_name=str(company[0].get("legal_name") or company[0].get("normalized_name") or ""),
            molecule_name=str(molecule[0].get("canonical_name") or ""), molecule_synonyms=tuple(molecule[0].get("synonyms") or ()),
            priority=str(row.get("priority") or ""), score=float(row.get("score") or 0),
        ))
    return targets


def run_molecule_discovery(settings: Any, *, client: Any = None, fetch_json: FetchJson | None = None,
                           provider_usage: ProviderUsage | None = None, persist: bool = True,
                           sleep: Callable[[float], None] = time.sleep) -> dict[str, Any]:
    """Daily-runner stage: discover and (optionally) persist for HOT/HIGH opportunities."""
    if not getattr(settings, "molecule_discovery_enabled", False):
        return {"status": "SKIPPED", "reason": "molecule_discovery_disabled", "processed": 0}
    if client is None:
        if not getattr(settings, "supabase_url", None) or not getattr(settings, "supabase_secret_key", None):
            return {"status": "SKIPPED", "reason": "supabase_credentials_missing", "processed": 0}
        from supabase import create_client
        client = create_client(settings.supabase_url, settings.supabase_secret_key)
    fetch = PoliteFetcher(
        fetch_json or (lambda url, headers: http_get_json(url, headers, timeout=float(getattr(settings, "request_timeout_seconds", 20.0)))),
        user_agent=str(getattr(settings, "user_agent", "SVAK-Impurity-Lead-Research/0.1")),
        delay_seconds=float(getattr(settings, "per_domain_delay_seconds", 1.0)),
        max_requests=int(getattr(settings, "molecule_discovery_max_requests", 120)),
        usage=provider_usage, sleep=sleep,
    )
    api_key = getattr(settings, "patentsview_api_key", None)
    totals: dict[str, Any] = {"status": "COMPLETED", "processed": 0, "sources": 0, "links": 0, "new_contacts": 0,
                              "patentsview": "ENABLED" if api_key else "SKIPPED_NO_KEY", "opportunities": []}
    for target in load_targets(client, limit=int(getattr(settings, "molecule_discovery_max_opportunities", 10))):
        if provider_usage is not None:
            provider_usage.record("europe_pmc", jobs=1)
        result = discover_for_opportunity(target, fetch, max_papers=int(getattr(settings, "molecule_discovery_max_papers", 10)), patentsview_api_key=api_key)
        metrics = persist_opportunity(client, result) if persist else {"people": len(result["people"])}
        totals["processed"] += 1
        totals["sources"] += metrics.get("sources", 0)
        totals["links"] += metrics.get("links", 0)
        totals["new_contacts"] += metrics.get("new_contacts", 0)
        totals["opportunities"].append({
            "opportunity_id": target.opportunity_id, "company": target.company_name, "molecule": target.molecule_name,
            **metrics, "errors": result["errors"],
            "people_found": [{"name": person.name, "employment": person.employment, "newest_source_date": person.newest_date,
                              "molecule_match": person.molecule_match, "evidence": sorted({item.kind for item in person.evidence}),
                              "role_fit": score} for person, score in result["people"]],
        })
        if any(error == "RuntimeError" for error in result["errors"].values()) and fetch.requests >= fetch.max_requests:
            totals["status"] = "PARTIAL"
            totals["stop_reason"] = "request_budget_exhausted"
            break
    totals["requests"] = fetch.requests
    return totals
