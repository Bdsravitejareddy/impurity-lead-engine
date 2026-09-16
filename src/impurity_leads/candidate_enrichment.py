"""Bounded evidence enrichment for retained company/molecule candidates.

This module deliberately reuses the normal signal classifier and Supabase
store.  It does not accept a caller-supplied score: the candidate is rebuilt
from all persisted signals, then promoted only through ``save_opportunity``.
"""
from __future__ import annotations

from typing import Any, Iterable

from impurity_leads.aggregate import aggregate_candidates
from impurity_leads.models import Signal, SourceRecord, Opportunity
from impurity_leads.pipeline import _record_signals
from impurity_leads.storage.supabase_store import SupabaseLeadStore, _stable_uuid


def _rows(client: Any, table: str, *, company_id: str, molecule_id: str) -> list[dict[str, Any]]:
    response = (
        client.table(table)
        .select("*")
        .eq("company_id", company_id)
        .eq("molecule_id", molecule_id)
        .execute()
    )
    return list(getattr(response, "data", None) or [])


def enrich_candidate(
    client: Any,
    *,
    company_id: str,
    molecule_id: str,
    company_name: str,
    molecule_name: str,
    records: Iterable[SourceRecord],
) -> dict[str, Any]:
    """Persist bounded new evidence and deterministically rescore one pair.

    ``records`` must contain only publicly inspected, accepted source records
    for the requested pair.  Repeated records are idempotent by signal
    fingerprint.  A candidate is promoted only when the aggregate of all
    persisted signals reaches the established threshold.
    """
    store = SupabaseLeadStore(client)
    before_rows = _rows(client, "company_molecules", company_id=company_id, molecule_id=molecule_id)
    if not before_rows:
        raise ValueError("candidate_not_found")
    before = dict(before_rows[0])
    existing_signal_rows = _rows(client, "signals", company_id=company_id, molecule_id=molecule_id)
    existing_fingerprints = {str(row.get("fingerprint")) for row in existing_signal_rows}
    new_signals = 0
    duplicate_signals = 0
    accepted_fingerprints: list[str] = []

    for record in records:
        for signal in _record_signals(record):
            if signal.company_name != company_name or signal.molecule_name != molecule_name:
                continue
            accepted_fingerprints.append(signal.fingerprint)
            if signal.fingerprint in existing_fingerprints:
                duplicate_signals += 1
                continue
            store.save_signal(signal)
            existing_fingerprints.add(signal.fingerprint)
            new_signals += 1

    all_rows = _rows(client, "signals", company_id=company_id, molecule_id=molecule_id)
    all_signals = [
        Signal.model_validate({**row, "company_name": company_name, "molecule_name": molecule_name})
        for row in all_rows
    ]
    candidates = aggregate_candidates(all_signals)
    candidate = next(
        (row for row in candidates if row["company_name"] == company_name and row["molecule_name"] == molecule_name),
        None,
    )
    if candidate is None:
        raise ValueError("candidate_not_resolved")
    store.save_candidate(candidate)
    promoted = bool(candidate.get("priority"))
    if promoted:
        store.save_opportunity(Opportunity(**candidate))

    opportunity_id = str(_stable_uuid("opportunity", f"{company_id}:{molecule_id}")) if promoted else None
    return {
        "company_id": company_id,
        "molecule_id": molecule_id,
        "before_score": before.get("candidate_score"),
        "before_status": before.get("candidate_status"),
        "after_score": candidate.get("score"),
        "after_status": "QUALIFIED" if promoted else "UNQUALIFIED",
        "priority": candidate.get("priority"),
        "new_signals": new_signals,
        "duplicate_signals_prevented": duplicate_signals,
        "accepted_fingerprints": accepted_fingerprints,
        "promoted": promoted,
        "opportunity_id": opportunity_id,
    }
