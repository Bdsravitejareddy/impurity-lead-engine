"""Bounded opportunity-directed contact research orchestration.

This module is provider-neutral: providers discover candidates, while the
caller owns source validation, canonical writes and graph persistence.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Protocol

from impurity_leads.contact_quality import QualityConfig, score_contact
from impurity_leads.research_discovery import SearchRequest, SearchResult, dedupe_results


MISSING_DIMENSIONS = (
    "PERSON_IDENTITY", "CURRENT_COMPANY", "CURRENT_ROLE", "INSTITUTION_AFFILIATION",
    "PERSON_COMPANY_RELATIONSHIP", "PERSON_PUBLICATION_RELATIONSHIP", "SENIORITY",
    "PROFESSIONAL_PROFILE", "COMPANY_IDENTITY", "CONTACTABILITY",
)


class TargetedSearchProvider(Protocol):
    name: str

    def discover(self, request: SearchRequest) -> list[SearchResult]: ...


@dataclass(frozen=True)
class TargetedSearchBudget:
    normal_rounds: int = 2
    high_value_rounds: int = 5
    max_results_per_round: int = 5
    max_sources: int = 20
    min_marginal_quality_gain: float = 3.0


@dataclass
class OpportunityCoverage:
    opportunity_id: str
    candidate_contact_count: int = 0
    qualified_contact_count: int = 0
    best_contact_score: float = 0.0
    identity_coverage: float = 0.0
    company_coverage: float = 0.0
    role_coverage: float = 0.0
    technical_relevance_coverage: float = 0.0
    evidence_strength: float = 0.0
    decision_maker_coverage: float = 0.0
    coverage_status: str = "NO_CONTACT"
    missing_dimensions: list[str] = field(default_factory=list)


def _is_qualified(contact: dict[str, Any], opportunity: dict[str, Any], config: QualityConfig) -> bool:
    scored = score_contact({**contact, "opportunity_fit": contact.get("opportunity_fit", 80)}, opportunities=[opportunity])
    return scored["score"] >= config.min_contact_quality and scored["identity_confidence"] >= config.min_identity_confidence and scored["technical_relevance"] >= config.min_technical_relevance


def evaluate_opportunity_coverage(opportunity: dict[str, Any], contacts: Iterable[dict[str, Any]], *, config: QualityConfig = QualityConfig()) -> OpportunityCoverage:
    rows = list(contacts)
    opportunity_id = str(opportunity.get("id") or opportunity.get("opportunity_id") or "")
    coverage = OpportunityCoverage(opportunity_id=opportunity_id, candidate_contact_count=len(rows))
    if not rows:
        coverage.missing_dimensions = ["PERSON_IDENTITY", "CURRENT_ROLE", "PROFESSIONAL_PROFILE", "CONTACTABILITY"]
        coverage.coverage_status = "NO_CONTACT"
        return coverage
    scored = [score_contact({**row, "opportunity_fit": row.get("opportunity_fit", 80)}, opportunities=[opportunity]) for row in rows]
    coverage.best_contact_score = max(item["score"] for item in scored)
    coverage.qualified_contact_count = sum(_is_qualified(row, opportunity, config) for row in rows)
    coverage.identity_coverage = sum(item["identity_confidence"] >= config.min_identity_confidence for item in scored) / len(rows)
    coverage.company_coverage = sum(bool(row.get("company_id") or row.get("company") or row.get("company_name")) for row in rows) / len(rows)
    coverage.role_coverage = sum(item["dimensions"]["current_role"] >= config.min_identity_confidence for item in scored) / len(rows)
    coverage.technical_relevance_coverage = sum(item["technical_relevance"] >= config.min_technical_relevance for item in scored) / len(rows)
    coverage.evidence_strength = sum(item["dimensions"]["source_independence"] for item in scored) / len(rows)
    coverage.decision_maker_coverage = sum(bool(row.get("seniority") or row.get("decision_maker")) for row in rows) / len(rows)
    if coverage.qualified_contact_count:
        coverage.coverage_status = "QUALIFIED"
    elif coverage.identity_coverage < 1:
        coverage.coverage_status = "IDENTITY_MISSING"
    else:
        coverage.coverage_status = "PARTIAL_CONTACT"
    if coverage.identity_coverage < 1:
        coverage.missing_dimensions.append("PERSON_IDENTITY")
    if coverage.company_coverage < 1:
        coverage.missing_dimensions.append("CURRENT_COMPANY")
    if coverage.role_coverage < 1:
        coverage.missing_dimensions.append("CURRENT_ROLE")
    if coverage.technical_relevance_coverage < 1:
        coverage.missing_dimensions.append("TECHNICAL_RELEVANCE")
    if coverage.evidence_strength < 50:
        coverage.missing_dimensions.append("SOURCE_INDEPENDENCE")
    if coverage.decision_maker_coverage < 1:
        coverage.missing_dimensions.append("SENIORITY")
    return coverage


def targeted_query_plan(opportunity: dict[str, Any], coverage: OpportunityCoverage, *, max_queries: int = 5) -> list[SearchRequest]:
    company = str(opportunity.get("company_name") or opportunity.get("company") or "").strip()
    molecule = str(opportunity.get("molecule_name") or opportunity.get("molecule") or "").strip()
    signal = str(opportunity.get("signal") or opportunity.get("likely_need_type") or opportunity.get("technical_signal") or "").strip()
    seed = " ".join(part for part in (company, molecule, signal) if part)
    plans: list[SearchRequest] = []
    for dimension in coverage.missing_dimensions:
        if dimension == "CURRENT_ROLE": query = f'"{company}" {molecule} analytical quality director'
        elif dimension in {"PERSON_IDENTITY", "PROFESSIONAL_PROFILE"}: query = f'"{company}" {molecule} author analytical impurity'
        elif dimension == "CONTACTABILITY": query = f'"{company}" analytical development contact'
        elif dimension == "SENIORITY": query = f'"{company}" head director analytical quality'
        elif dimension == "SOURCE_INDEPENDENCE": query = f'"{seed}" official publication patent'
        else: query = f'"{seed}" {dimension.casefold().replace("_", " ")}'
        plans.append(SearchRequest(query=" ".join(query.split()), seed_type="OPPORTUNITY", seed_id=str(opportunity.get("id") or ""), target_dimension=dimension, max_results=5))
        if len(plans) >= max_queries: break
    return plans


def run_targeted_rounds(
    opportunity: dict[str, Any],
    contacts: list[dict[str, Any]],
    provider: TargetedSearchProvider,
    *,
    accept_result: Callable[[SearchResult, SearchRequest], dict[str, Any] | None],
    config: QualityConfig = QualityConfig(),
    budget: TargetedSearchBudget = TargetedSearchBudget(),
) -> dict[str, Any]:
    """Run bounded rounds until coverage qualifies or evidence stops improving."""
    before = evaluate_opportunity_coverage(opportunity, contacts, config=config)
    high_value = float(opportunity.get("score") or 0) >= config.deep_research_opportunity_threshold
    max_rounds = budget.high_value_rounds if high_value else budget.normal_rounds
    rounds: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    current = before
    for round_number in range(1, max_rounds + 1):
        if current.coverage_status == "QUALIFIED":
            return {"status": "QUALIFIED", "stop_reason": "QUALIFIED", "coverage": current, "rounds": rounds}
        requests = targeted_query_plan(opportunity, current, max_queries=1)
        if not requests:
            return {"status": "STOPPED", "stop_reason": "NO_SEARCHABLE_DIMENSION", "coverage": current, "rounds": rounds}
        request = requests[0]
        try:
            found = dedupe_results(provider.discover(request))[:budget.max_sources]
        except Exception as exc:
            rounds.append({"round": round_number, "dimension": request.target_dimension, "queries": [request.query], "error": type(exc).__name__, "new_sources": 0})
            return {"status": "PARTIAL", "stop_reason": "PROVIDER_ERROR", "coverage": current, "rounds": rounds}
        accepted = 0
        for result in found:
            if result.url in seen_urls:
                continue
            seen_urls.add(result.url)
            if accept_result(result, request):
                accepted += 1
        after = evaluate_opportunity_coverage(opportunity, contacts, config=config)
        rounds.append({"round": round_number, "dimension": request.target_dimension, "queries": [request.query], "new_sources": len(found), "accepted": accepted, "score_before": current.best_contact_score, "score_after": after.best_contact_score, "coverage_before": current.coverage_status, "coverage_after": after.coverage_status})
        if after.coverage_status == "QUALIFIED":
            return {"status": "QUALIFIED", "stop_reason": "QUALIFIED", "coverage": after, "rounds": rounds}
        if accepted == 0 or after.best_contact_score - current.best_contact_score < budget.min_marginal_quality_gain:
            return {"status": "STOPPED", "stop_reason": "DIMINISHING_RETURNS" if accepted else "NO_NEW_EVIDENCE", "coverage": after, "rounds": rounds}
        current = after
    return {"status": "STOPPED", "stop_reason": "MAX_ROUNDS", "coverage": current, "rounds": rounds}
