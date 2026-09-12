"""Deterministic, evidence-backed molecule intelligence read-model helpers."""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable

CLAIM_TYPES = {
    "IDENTITY", "WHAT_IT_IS", "CLINICAL_USE", "MECHANISM", "CLINICAL_SAFETY",
    "TOXICOLOGY", "HAZARD", "IMPURITY", "DEGRADATION", "GENOTOXICITY",
    "NITROSAMINE", "ANALYTICAL_RELEVANCE", "SVAK_RELEVANCE",
}

SECTION_TYPES = (
    "SUMMARY", "WHAT_IT_IS", "CLINICAL_USE", "MECHANISM", "CLINICAL_SAFETY",
    "TOX_HAZARD", "IMPURITY_RELEVANCE", "SVAK_RELEVANCE", "UNKNOWNS",
)
SOURCE_CLASS_RANK = {"PRIMARY": 4, "STRONG_PROFESSIONAL": 3, "DIRECTORY": 2, "DISCOVERY_WEAK": 1}
RESEARCH_DIMENSIONS = ("WHAT_IT_IS", "CLINICAL_USE", "CLINICAL_SAFETY", "TOXICOLOGY", "IMPURITY_RELEVANCE", "ANALYTICAL_RELEVANCE")


def normalize_claim_type(value: Any) -> str:
    value = str(value or "").strip().upper().replace(" ", "_").replace("-", "_")
    aliases = {"TOX_HAZARD": "TOXICOLOGY", "IMPURITY_RELEVANCE": "IMPURITY", "DEGRADATION_RELEVANCE": "DEGRADATION"}
    return aliases.get(value, value if value in CLAIM_TYPES else "OTHER")


def missing_molecule_dimensions(sections: Iterable[dict[str, Any]]) -> list[str]:
    by_type = {str(section.get("section_type")): section for section in sections or []}
    return [dimension for dimension in RESEARCH_DIMENSIONS if (by_type.get(dimension) or (by_type.get("TOX_HAZARD") if dimension == "TOXICOLOGY" else {}) or {}).get("evidence_status") != "SUPPORTED"]


def _section_for_claim(claim_type: str) -> str | None:
    return {
        "IDENTITY": "WHAT_IT_IS", "WHAT_IT_IS": "WHAT_IT_IS", "CLINICAL_USE": "CLINICAL_USE",
        "MECHANISM": "MECHANISM", "CLINICAL_SAFETY": "CLINICAL_SAFETY", "TOXICOLOGY": "TOX_HAZARD",
        "HAZARD": "TOX_HAZARD", "GENOTOXICITY": "TOX_HAZARD", "IMPURITY": "IMPURITY_RELEVANCE",
        "DEGRADATION": "IMPURITY_RELEVANCE", "NITROSAMINE": "IMPURITY_RELEVANCE",
        "ANALYTICAL_RELEVANCE": "IMPURITY_RELEVANCE", "SVAK_RELEVANCE": "SVAK_RELEVANCE",
    }.get(claim_type)


def build_intelligence_sections(claims: Iterable[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for claim in claims or []:
        section = _section_for_claim(normalize_claim_type(claim.get("claim_type")))
        if section:
            grouped[section].append(claim)
    output: dict[str, dict[str, Any]] = {}
    for section in SECTION_TYPES:
        rows = grouped.get(section, [])
        rows = sorted(rows, key=lambda item: (SOURCE_CLASS_RANK.get(str(item.get("source_class") or "DISCOVERY_WEAK"), 0), float(item.get("confidence") or 0)), reverse=True)
        statements = [str(item.get("claim_text") or item.get("claim") or "").strip() for item in rows]
        statements = [item for item in statements if item]
        ids = [str(item.get("id")) for item in rows if item.get("id")]
        sources = {str(item.get("source_id") or item.get("source_url")) for item in rows if item.get("source_id") or item.get("source_url")}
        status = "SUPPORTED" if rows and any(item.get("provenance") == "OBSERVED" for item in rows) else "PARTIAL" if rows else "UNKNOWN"
        output[section] = {
            "summary_text": " ".join(statements[:3]) if statements else ("Insufficient evidence to generate a reliable summary." if section != "UNKNOWNS" else "No validated evidence available."),
            "supporting_claim_ids": ids,
            "evidence_status": status,
            "source_count": len(sources),
            "confidence": max((float(item.get("confidence") or 0) for item in rows), default=0.0),
        }
    known = {key for key, value in output.items() if value["evidence_status"] != "UNKNOWN"}
    unknowns = [section for section in SECTION_TYPES if section not in known and section not in {"SUMMARY", "UNKNOWNS"}]
    output["UNKNOWNS"] = {**output["UNKNOWNS"], "summary_text": ", ".join(unknowns) if unknowns else "No material evidence gaps recorded."}
    summary_parts = [output[key]["summary_text"] for key in ("WHAT_IT_IS", "CLINICAL_USE", "IMPURITY_RELEVANCE") if output[key]["evidence_status"] != "UNKNOWN"]
    output["SUMMARY"] = {
        "summary_text": " ".join(summary_parts[:3]) if summary_parts else "Insufficient evidence to generate a reliable summary.",
        "supporting_claim_ids": [claim_id for key in ("WHAT_IT_IS", "CLINICAL_USE", "IMPURITY_RELEVANCE") for claim_id in output[key]["supporting_claim_ids"]],
        "evidence_status": "SUPPORTED" if summary_parts else "UNKNOWN",
        "source_count": sum(output[key]["source_count"] for key in ("WHAT_IT_IS", "CLINICAL_USE", "IMPURITY_RELEVANCE")),
        "confidence": max((output[key]["confidence"] for key in ("WHAT_IT_IS", "CLINICAL_USE", "IMPURITY_RELEVANCE")), default=0.0),
    }
    return output


def apply_molecule_sections(client: Any, molecule_id: str, claims: list[dict[str, Any]], *, generation_version: int = 1) -> dict[str, Any]:
    sections = build_intelligence_sections(claims)
    written = 0
    for section_type, section in sections.items():
        payload = {"molecule_id": molecule_id, "section_type": section_type, "summary_text": section["summary_text"], "supporting_claim_ids": section["supporting_claim_ids"], "evidence_status": section["evidence_status"], "source_count": section["source_count"], "confidence": section["confidence"], "generation_version": generation_version}
        client.table("molecule_intelligence_sections").upsert(payload, on_conflict="molecule_id,section_type").execute()
        written += 1
    return {"sections_written": written, "sections": sections}
