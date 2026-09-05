from impurity_leads.aggregate import aggregate_opportunities
from impurity_leads.classify import classify_signal, looks_like_impurity_vendor
from impurity_leads.dedupe import signal_fingerprint
from impurity_leads.models import Opportunity, Signal, SourceRecord
from impurity_leads.normalize import normalize_company_name, normalize_molecule_name
from impurity_leads.storage.base import LeadStore

_PHASE_WEIGHTS = {"PHASE3": 18, "PHASE2": 12}


def _record_signals(record: SourceRecord) -> list[Signal]:
    if not record.company_name_raw:
        return []
    company_display = record.company_name_raw.strip()
    company_key = normalize_company_name(company_display)
    molecule_display = (record.molecule_name_raw or record.active_ingredient_raw or "").strip() or None
    molecule_key = normalize_molecule_name(molecule_display) if molecule_display else None
    discovered_at = record.fetched_at
    output: list[Signal] = []

    vendor = bool(record.metadata_json.get("is_impurity_vendor")) or looks_like_impurity_vendor(record.signal_text)
    if vendor:
        kind = "impurity_vendor_exclusion"
        output.append(
            Signal(
                company_name=company_display,
                molecule_name=molecule_display,
                source_type=record.source_type,
                signal_type=kind,
                source_url=record.source_url,
                source_record_id=record.source_record_id,
                evidence_text=record.signal_text[:800],
                event_date=record.published_at,
                discovered_at=discovered_at,
                base_weight=-100,
                confidence=1.0,
                fingerprint=signal_fingerprint(company_key, molecule_key, kind, record.source_url, record.signal_text[:800]),
                metadata_json={"excluded_vendor": True},
            )
        )
        return output

    for signal_type, weight, need_type in classify_signal(record.signal_text, has_molecule=bool(molecule_display)):
        output.append(
            Signal(
                company_name=company_display,
                molecule_name=molecule_display,
                source_type=record.source_type,
                signal_type=signal_type,
                source_url=record.source_url,
                source_record_id=record.source_record_id,
                evidence_text=record.signal_text[:800],
                event_date=record.published_at,
                discovered_at=discovered_at,
                base_weight=weight,
                confidence=1.0,
                fingerprint=signal_fingerprint(company_key, molecule_key, signal_type, record.source_url, record.signal_text[:800]),
                metadata_json={"need_type": need_type, **record.metadata_json},
            )
        )

    phase = str(record.metadata_json.get("phase") or "").upper()
    if molecule_display and phase in _PHASE_WEIGHTS:
        signal_type = "phase_iii" if phase == "PHASE3" else "phase_ii"
        output.append(
            Signal(
                company_name=company_display,
                molecule_name=molecule_display,
                source_type=record.source_type,
                signal_type=signal_type,
                source_url=record.source_url,
                source_record_id=record.source_record_id,
                evidence_text=record.signal_text[:800],
                event_date=record.published_at,
                discovered_at=discovered_at,
                base_weight=_PHASE_WEIGHTS[phase],
                confidence=1.0,
                fingerprint=signal_fingerprint(company_key, molecule_key, signal_type, record.source_url, record.signal_text[:800]),
                metadata_json={"need_type": "late-stage development", **record.metadata_json},
            )
        )

    application = record.metadata_json.get("application_number")
    if molecule_display and application:
        signal_type = "regulatory_application"
        output.append(
            Signal(
                company_name=company_display,
                molecule_name=molecule_display,
                source_type=record.source_type,
                signal_type=signal_type,
                source_url=record.source_url,
                source_record_id=record.source_record_id,
                evidence_text=record.signal_text[:800],
                event_date=record.published_at,
                discovered_at=discovered_at,
                base_weight=22,
                confidence=1.0,
                fingerprint=signal_fingerprint(company_key, molecule_key, signal_type, record.source_url, record.signal_text[:800]),
                metadata_json={"need_type": "regulatory/CMC activity", **record.metadata_json},
            )
        )
    return output


def process_records(records: list[SourceRecord], store: LeadStore) -> list[Opportunity]:
    all_signals: list[Signal] = []
    vendor_companies: set[str] = set()

    for record in records:
        record_signals = _record_signals(record)
        for signal in record_signals:
            store.save_signal(signal)
            all_signals.append(signal)
            if signal.signal_type == "impurity_vendor_exclusion":
                vendor_companies.add(normalize_company_name(signal.company_name))

    qualified_signals = [
        signal
        for signal in all_signals
        if normalize_company_name(signal.company_name) not in vendor_companies
        and signal.signal_type != "impurity_vendor_exclusion"
    ]
    opportunities = aggregate_opportunities(qualified_signals)
    for opportunity in opportunities:
        store.save_opportunity(opportunity)
    return opportunities
