"""Conservative, provenance-aware role intelligence inference.

This module never creates observed claims.  It turns a current title and
department into clearly labelled hypotheses that help operators understand a
profile until person-specific public evidence is available.
"""

from __future__ import annotations

import re
from typing import Any
from uuid import NAMESPACE_URL, uuid5


ROLE_ONTOLOGY_VERSION = "ROLE_ONTOLOGY_V1"

_ROLE_FAMILIES: list[dict[str, Any]] = [
    {
        "name": "analytical_quality",
        "terms": ("analytical", "quality control", "quality", "qc", "laboratory", "lab", "method validation"),
        "themes": ("analytical development", "quality control", "method validation", "impurity characterization", "stability testing"),
        "problems": ("maintaining reliable analytical methods", "controlling impurities and degradation products", "managing laboratory data integrity"),
        "jtbd": ("Define and maintain analytical methods for identity, purity, impurities and degradation products.", "Review laboratory results, investigations and method performance for release or stability decisions.", "Coordinate analytical quality priorities with internal laboratories and external technical partners."),
        "mapping": "Analytical method development, impurity characterization, stability and reference-standard support.",
    },
    {
        "name": "qa_compliance",
        "terms": ("quality assurance", "qa", "compliance", "gmp", "validation", "data integrity"),
        "themes": ("quality assurance", "GMP compliance", "validation", "data integrity", "deviation and CAPA oversight"),
        "problems": ("maintaining compliant quality systems", "reviewing deviations, CAPA and audit readiness", "ensuring validated data supports regulated decisions"),
        "jtbd": ("Ensure quality systems and analytical records support compliant product decisions.", "Review deviations, CAPA and validation evidence with the responsible technical teams.", "Assess external technical work for quality-system and regulatory fit."),
        "mapping": "Quality systems, compliance, validation and regulated technical evidence.",
    },
    {
        "name": "cmc_process",
        "terms": ("cmc", "process development", "process chemistry", "api development", "technical operations", "tech ops", "manufacturing science"),
        "themes": ("CMC", "process development", "scale-up", "process impurity control", "technical operations"),
        "problems": ("scaling a robust process", "controlling process-related impurities", "transferring technical methods into manufacturing"),
        "jtbd": ("Develop and transfer robust processes with defined impurity and degradation controls.", "Evaluate process data and analytical evidence during scale-up or technical transfer.", "Coordinate specialist external support for process, impurity or stability work."),
        "mapping": "Process impurity, degradation, scale-up and technical-transfer support.",
    },
    {
        "name": "regulatory",
        "terms": ("regulatory", "reg affairs", "submission", "registration"),
        "themes": ("regulatory CMC", "submission support", "health-authority responses", "product lifecycle management"),
        "problems": ("assembling defensible CMC evidence", "answering regulator questions", "maintaining consistent technical documentation"),
        "jtbd": ("Assemble and maintain technical evidence required for regulatory submissions and responses.", "Identify evidence gaps in impurity, stability and analytical documentation.", "Coordinate technical contributors so submitted quality information is consistent and traceable."),
        "mapping": "Regulatory CMC, impurity evidence, analytical documentation and submission support.",
    },
    {
        "name": "procurement",
        "terms": ("procurement", "sourcing", "purchasing", "buyer", "supplier", "vendor management"),
        "themes": ("technical sourcing", "supplier qualification", "vendor management", "cost and continuity"),
        "problems": ("qualifying reliable technical suppliers", "balancing cost, quality and continuity", "maintaining supplier documentation"),
        "jtbd": ("Identify and qualify suppliers for technically critical materials and services.", "Compare supplier capability, quality evidence, delivery risk and commercial fit.", "Coordinate procurement decisions with analytical, quality and regulatory stakeholders."),
        "mapping": "Supplier qualification, impurity/reference-standard sourcing and technical procurement.",
    },
    {
        "name": "executive",
        "terms": ("chief", "ceo", "cfo", "coo", "vice president", "vp", "president", "general manager", "global head", "head of"),
        "themes": ("functional strategy", "portfolio governance", "cross-functional prioritisation", "external partnership decisions"),
        "problems": ("prioritising functional risk and investment", "aligning technical, quality and commercial stakeholders", "governing external partnerships"),
        "jtbd": ("Set priorities and allocate resources across the quality, analytical or technical function.", "Evaluate strategic risk, capability gaps and external partnership options.", "Align functional execution with product, compliance and commercial objectives."),
        "mapping": "Strategic quality, analytical capability, risk and partnership discussions.",
    },
]


def _matching_family(title: str | None, department: str | None) -> tuple[dict[str, Any] | None, int]:
    text = f"{title or ''} {department or ''}".casefold()
    best: tuple[int, dict[str, Any]] | None = None
    for family in _ROLE_FAMILIES:
        score = sum(1 for term in family["terms"] if re.search(rf"\b{re.escape(term)}\b", text))
        if score and (best is None or score > best[0]):
            best = (score, family)
    return (best[1], best[0]) if best else (None, 0)


def role_level(title: str | None) -> str:
    text = (title or "").casefold()
    if re.search(r"\b(chief|ceo|cfo|coo|president|vice president|vp|global head|head of)\b", text):
        return "EXECUTIVE_OR_FUNCTION_HEAD"
    if re.search(r"\b(director|associate director|senior director)\b", text):
        return "DIRECTOR"
    if re.search(r"\b(manager|lead|principal)\b", text):
        return "MANAGER_OR_LEAD"
    if re.search(r"\b(senior|scientist|engineer|analyst|specialist|officer)\b", text):
        return "INDIVIDUAL_OR_SENIOR_PROFESSIONAL"
    return "UNKNOWN"


def infer_role_intelligence(contact: dict[str, Any], existing_statements: set[str] | None = None) -> dict[str, Any]:
    """Return idempotent inferred JTBD/themes/problems for one contact."""
    family, matches = _matching_family(contact.get("title"), contact.get("department"))
    if not family:
        return {"family": None, "confidence": 0.0, "level": role_level(contact.get("title")), "jtbd": [], "themes": [], "problems": []}
    existing = {item.casefold() for item in (existing_statements or set())}
    # A specific title/department match is stronger than a generic department
    # match, but remains an inference and never becomes an observed claim.
    confidence = min(0.72, 0.52 + matches * 0.08)
    basis = f"{ROLE_ONTOLOGY_VERSION}; title/department match"
    jtbd = []
    for statement in family["jtbd"]:
        if statement.casefold() in existing:
            continue
        jtbd.append({
            "id": str(uuid5(NAMESPACE_URL, f"svak:role-jtbd:{contact.get('id')}:{statement}")),
            "statement": statement,
            "category": family["name"],
            "basis": basis,
            "evidence": "Derived from role taxonomy; independently verify with person-specific public evidence.",
            "confidence": confidence,
            "provenance": "INFERRED",
            "svak_mapping": family["mapping"],
            "discovery_question": "Is this an active responsibility or requirement for your team today?",
            "source_ids": [],
        })
    return {
        "family": family["name"],
        "confidence": confidence,
        "level": role_level(contact.get("title")),
        "basis": basis,
        "jtbd": jtbd,
        "themes": list(family["themes"]),
        "problems": list(family["problems"]),
    }
