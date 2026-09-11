"""Bounded relational evidence-graph primitives.

The graph is represented in PostgreSQL tables, while this module keeps query
planning, entity normalization and claim fusion deterministic and testable.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata
from typing import Any, Iterable


@dataclass(frozen=True)
class ResearchBudget:
    max_queries: int = 30
    max_sources: int = 50
    max_documents: int = 20
    max_people: int = 20
    max_depth: int = 3
    max_ai_analysis_calls: int = 20
    max_ai_search_calls: int = 8
    max_ai_deep_calls: int = 3
    max_sources_per_person: int = 10
    min_marginal_quality_gain: float = 3.0
    max_run_minutes: int = 40


def normalize_entity_name(value: str) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return " ".join(re.sub(r"[^\w\s-]", " ", text).split())


def bounded_query_plan(seeds: Iterable[dict[str, Any]], budget: ResearchBudget = ResearchBudget()) -> list[dict[str, Any]]:
    """Expand only high-value seeds to depth 1–3 with URL/query dedupe."""
    planned: list[dict[str, Any]] = []; seen: set[str] = set()
    for seed in seeds:
        name = str(seed.get("name") or seed.get("canonical_name") or "").strip()
        if not name: continue
        kind = str(seed.get("entity_type") or "OTHER").upper(); depth = int(seed.get("depth", 0))
        if depth >= budget.max_depth: continue
        terms = [name]
        if kind == "MOLECULE": terms += [f"{name} impurity", f"{name} degradation", f"{name} related substances", f"{name} impurity synthesis", f"{name} stability indicating", f"{name} LC-MS"]
        elif kind == "PERSON": terms += [f"{name} publication", f"{name} patent", f"{name} analytical", f"{name} conference"]
        elif kind == "COMPANY": terms += [f"{name} quality impurity", f"{name} analytical development"]
        elif kind == "OPPORTUNITY": terms += [f"{name} technical evidence", f"{name} impurity synthesis", f"{name} degradation product"]
        for query in terms:
            key = " ".join(query.casefold().split())
            if key in seen or len(planned) >= budget.max_queries: continue
            seen.add(key); planned.append({"query": query, "seed": name, "entity_type": kind, "depth": depth + 1})
    return planned


def extract_claims(text: str, *, source_id: str, source_url: str, attribution: str = "COMPANY_CONTEXT") -> list[dict[str, Any]]:
    """Extract conservative technical claims without inventing people."""
    lower = text.casefold(); claims: list[dict[str, Any]] = []
    terms = {"impurity": "impurity control", "degradation": "degradation-product work", "stability": "stability support", "related substance": "related-substances analysis", "nitrosamine": "nitrosamine control", "method validation": "analytical method validation"}
    for term, label in terms.items():
        if term in lower:
            claims.append({"claim": f"Source discusses {label}.", "source_id": source_id, "source_url": source_url, "attribution": attribution, "provenance": "OBSERVED", "confidence": 0.72, "support_text": text[:500]})
    return claims


def fuse_claims(claims: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Group equivalent claims while preserving support and contradiction."""
    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    for item in claims:
        key = (normalize_entity_name(item.get("entity") or ""), normalize_entity_name(item.get("claim") or ""))
        if key not in grouped:
            grouped[key] = {**item, "supporting_sources": [], "contradicting_sources": []}
        target = grouped[key]["contradicting_sources" if item.get("contradicts") else "supporting_sources"]
        if item.get("source_id") and item["source_id"] not in target: target.append(item["source_id"])
        grouped[key].setdefault("supporting_classes", set()).add(str(item.get("source_class") or "UNKNOWN")) if not item.get("contradicts") else None
    for item in grouped.values():
        classes = item.pop("supporting_classes", set())
        independent_bonus = min(0.20, max(0, len(classes) - 1) * 0.08)
        contradiction_penalty = min(0.25, len(item["contradicting_sources"]) * 0.10)
        item["confidence"] = min(0.99, max(0.0, float(item.get("confidence", 0.5)) + independent_bonus - contradiction_penalty))
        item["source_classes"] = sorted(classes)
    return list(grouped.values())


def publication_graph_entities(*, person: str, company: str, title: str) -> list[dict[str, Any]]:
    """Return canonical graph entity payloads for a publication finding."""
    rows = []
    for entity_type, name, metadata in (
        ("PERSON", person, {"role": "named author"}),
        ("COMPANY", company, {}),
        ("PUBLICATION", title, {}),
    ):
        if name and str(name).strip():
            rows.append({
                "entity_type": entity_type,
                "canonical_name": str(name).strip()[:500],
                "normalized_name": normalize_entity_name(name),
                "metadata_json": metadata,
            })
    return rows
