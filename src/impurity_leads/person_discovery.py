"""Conservative extraction and ranking of people from technical sources."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from impurity_leads.contacts.normalize import normalize_person_name, person_name_compatibility


@dataclass(frozen=True)
class PersonCandidate:
    name: str
    given_name: str | None
    family_name: str | None
    affiliation: str | None
    orcid: str | None
    author_order: int
    corresponding: bool
    source_date: str | None
    technical_relevance: float
    state: str = "DISCOVERED"


def publication_metadata(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "title": str(item.get("title") or "Technical publication")[:500],
        "pmid": item.get("pmid") or item.get("id"),
        "doi": item.get("doi") or item.get("doiId"),
        "pmcid": item.get("pmcid"),
        "journal": item.get("journalTitle") or item.get("journalInfo", {}).get("journal", {}).get("title"),
        "publication_date": item.get("firstPublicationDate") or item.get("pubYear"),
        "url": item.get("url"),
    }


def extract_authors(item: dict[str, Any], *, technical_text: str = "") -> list[PersonCandidate]:
    authors = (item.get("authorList") or {}).get("author") or item.get("authors") or []
    if isinstance(authors, dict):
        authors = [authors]
    if not authors and item.get("authorString"):
        authors = [{"fullName": name.strip()} for name in str(item["authorString"]).split(";") if name.strip()]
    lower = technical_text.casefold()
    technical = 85.0 if any(term in lower for term in ("impurity", "degradation", "stability", "analytical", "method validation", "nitrosamine")) else 65.0
    result: list[PersonCandidate] = []
    for index, author in enumerate(authors):
        if isinstance(author, str):
            author = {"fullName": author}
        name = str(author.get("fullName") or " ".join(filter(None, (author.get("firstName"), author.get("lastName"))))).strip()
        if not name or len(normalize_person_name(name).split()) < 2:
            continue
        affiliation = author.get("affiliation") or author.get("affiliationText")
        result.append(PersonCandidate(
            name=name[:250],
            given_name=author.get("firstName"),
            family_name=author.get("lastName"),
            affiliation=str(affiliation)[:1000] if affiliation else None,
            orcid=author.get("orcid") or author.get("ORCID"),
            author_order=index + 1,
            corresponding=bool(author.get("correspondingAuthor") or author.get("corresponding")),
            source_date=item.get("firstPublicationDate") or item.get("pubYear"),
            technical_relevance=technical,
            state="TECHNICALLY_RELEVANT" if technical >= 80 else "DISCOVERED",
        ))
    return result


def affiliation_matches_company(affiliation: str | None, company: str | None) -> bool:
    if not affiliation or not company:
        return False
    company_tokens = [token for token in normalize_person_name(company).split() if len(token) >= 4]
    text = normalize_person_name(affiliation)
    return bool(company_tokens) and sum(token in text for token in company_tokens) >= max(1, len(company_tokens) // 2)


def candidate_identity_state(candidate: PersonCandidate, existing: dict[str, Any] | None, *, company_match: bool) -> tuple[str, float, list[str]]:
    if not existing:
        return ("PROBABLE_SAME_PERSON" if company_match else "NEEDS_REVIEW", 78.0 if company_match else 45.0, ["source affiliation matches target company"] if company_match else [])
    compatibility = person_name_compatibility(str(existing.get("display_name") or ""), candidate.name)
    evidence = []
    if compatibility >= 0.78:
        evidence.append("name and initials are compatible")
    if company_match:
        evidence.append("source affiliation matches target company")
    if compatibility >= 0.78 and company_match:
        return "SAME_PERSON", min(98.0, 70.0 + compatibility * 20), evidence
    if compatibility >= 0.5 and company_match:
        return "PROBABLE_SAME_PERSON", 72.0, evidence
    return "NEEDS_REVIEW", 45.0, evidence


def rank_candidate(candidate: PersonCandidate, *, company_match: bool, current_role: bool = False) -> float:
    score = candidate.technical_relevance * 0.55
    score += 15 if company_match else 0
    score += 10 if current_role else 0
    score += 5 if candidate.corresponding else 0
    score += max(0, 10 - candidate.author_order)
    return round(min(100.0, score), 1)
