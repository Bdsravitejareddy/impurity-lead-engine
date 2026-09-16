"""Bounded Work research queue for retained company/molecule candidates."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from impurity_leads.agent_research import queue_opportunity_evidence_job

OPPORTUNITY_EVIDENCE_DIMENSIONS = (
    "IMPURITY_CHARACTERIZATION", "DEGRADATION_PRODUCT", "STABILITY",
    "REFERENCE_STANDARD", "GENOTOXIC_IMPURITY", "NITROSAMINE_NDSRI",
    "ANALYTICAL_METHOD", "REGULATORY_APPLICATION", "DIRECT_IMPURITY_RFQ",
)

_DIMENSION_SIGNAL_TYPES = {
    "IMPURITY_CHARACTERIZATION": {"impurity_characterization"},
    "DEGRADATION_PRODUCT": {"degradation_product"},
    "STABILITY": {"stability"},
    "REFERENCE_STANDARD": {"reference_standard"},
    "GENOTOXIC_IMPURITY": {"genotoxic_impurity"},
    "NITROSAMINE_NDSRI": {"nitrosamine_ndsri"},
    "ANALYTICAL_METHOD": {"method_validation"},
    "REGULATORY_APPLICATION": {"regulatory_application"},
    "DIRECT_IMPURITY_RFQ": {"direct_impurity_rfq"},
}


def missing_opportunity_dimensions(signals: list[dict[str, Any]]) -> list[str]:
    """Return only evidence dimensions absent from the persisted pair."""
    kinds = {str(row.get("signal_type") or "").lower() for row in signals}
    return [dimension for dimension in OPPORTUNITY_EVIDENCE_DIMENSIONS
            if not kinds.intersection(_DIMENSION_SIGNAL_TYPES[dimension])]


def rank_candidates(rows: list[dict[str, Any]], signals_by_fingerprint: dict[str, dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """Rank retained candidates by deterministic distance and evidence quality."""
    signals_by_fingerprint = signals_by_fingerprint or {}
    def key(row: dict[str, Any]):
        score = float(row.get("candidate_score") or 0)
        fps = row.get("candidate_signal_fingerprints") or []
        signals = [signals_by_fingerprint.get(str(fp), {}) for fp in fps]
        technical = sum(1 for signal in signals if str(signal.get("signal_type") or "") in {"impurity_characterization", "degradation_product", "reference_standard", "genotoxic_impurity", "nitrosamine_ndsri", "direct_impurity_rfq"})
        classes = len({str(signal.get("source_type") or "").lower() for signal in signals if signal.get("source_type")})
        return (score, technical, classes, len(signals), str(row.get("candidate_last_signal_at") or ""))
    return sorted(rows, key=key, reverse=True)


def _table_rows(client: Any, table: str, column: str, values: list[str]) -> list[dict[str, Any]]:
    if not values:
        return []
    try:
        return client.table(table).select("*").in_(column, values).execute().data or []
    except Exception:
        return []


def run_pending_opportunity_enrichment(settings: Any, *, limit: int = 2) -> dict[str, Any]:
    """Queue at most ``limit`` retained candidates for bounded Work research."""
    if not getattr(settings, "supabase_url", None) or not getattr(settings, "supabase_secret_key", None):
        return {"status": "SKIPPED", "reason": "supabase_credentials_missing", "selected": 0}
    from supabase import create_client
    client = create_client(settings.supabase_url, settings.supabase_secret_key)
    try:
        candidates = client.table("company_molecules").select("*").eq("candidate_status", "UNQUALIFIED").lt("candidate_score", 50).limit(500).execute().data or []
    except Exception as exc:
        return {"status": "FAILED", "reason": type(exc).__name__, "selected": 0}
    if not candidates or limit <= 0:
        return {"status": "COMPLETED", "selected": 0, "eligible": 0, "deduped": 0}
    company_ids = list({str(row.get("company_id")) for row in candidates if row.get("company_id")})
    molecule_ids = list({str(row.get("molecule_id")) for row in candidates if row.get("molecule_id")})
    companies = {str(row["id"]): row for row in _table_rows(client, "companies", "id", company_ids) if row.get("id")}
    molecules = {str(row["id"]): row for row in _table_rows(client, "molecules", "id", molecule_ids) if row.get("id")}
    fingerprints = [str(fp) for row in candidates for fp in (row.get("candidate_signal_fingerprints") or [])]
    signal_rows = _table_rows(client, "signals", "fingerprint", fingerprints)
    signals_by_fp = {str(row.get("fingerprint")): row for row in signal_rows}
    eligible = []
    for row in candidates:
        if not row.get("company_id") or not row.get("molecule_id"):
            continue
        dimensions = missing_opportunity_dimensions([signals_by_fp.get(str(fp), {}) for fp in (row.get("candidate_signal_fingerprints") or [])])
        if not dimensions:
            continue
        item = dict(row)
        item["missing_dimensions"] = dimensions[:2]
        item["_rank"] = (float(row.get("candidate_score") or 0), len(row.get("candidate_signal_fingerprints") or []))
        eligible.append(item)
    ranked = rank_candidates(eligible, signals_by_fp)
    selected = []
    deduped = 0
    for row in ranked:
        if len(selected) >= limit:
            break
        company = companies.get(str(row["company_id"]), {})
        molecule = molecules.get(str(row["molecule_id"]), {})
        job = queue_opportunity_evidence_job(
            client, candidate=row,
            company_name=company.get("legal_name") or company.get("normalized_name") or str(row["company_id"]),
            molecule_name=molecule.get("canonical_name") or str(row["molecule_id"]),
            missing_dimensions=row["missing_dimensions"],
            priority=int(row.get("candidate_score") or 0),
        )
        if job:
            if job.get("_deduped"):
                deduped += 1
            else:
                selected.append(job)
    return {"status": "COMPLETED", "selected": len(selected), "eligible": len(eligible), "deduped": deduped, "jobs": selected}
