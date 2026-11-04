from collections import Counter, defaultdict
from datetime import datetime

from impurity_leads.models import Opportunity, Signal
from impurity_leads.normalize import normalize_company_name, normalize_molecule_name
from impurity_leads.score import IMPURITY_SIGNAL_TYPES, score_signals

_ROLE_MAP = {
    "impurity_characterization": ["Head/Director Analytical R&D"],
    "degradation_product": ["Head/Director Analytical R&D"],
    "nitrosamine_ndsri": ["Analytical Development", "Quality", "Regulatory CMC"],
    "genotoxic_impurity": ["Analytical Development", "Regulatory CMC"],
    "reference_standard": ["Analytical R&D", "Strategic Sourcing/Procurement"],
    "direct_impurity_rfq": ["Analytical R&D", "Strategic Sourcing/Procurement"],
}


def _priority(score: int, signal_types: set[str]) -> str | None:
    if "direct_impurity_rfq" in signal_types:
        return "HOT"
    has_impurity_evidence = bool(signal_types & IMPURITY_SIGNAL_TYPES)
    if score >= 80 and has_impurity_evidence:
        return "HOT"
    if score >= 65 and has_impurity_evidence:
        return "HIGH"
    if score >= 50:
        return "REVIEW"
    return None


def aggregate_opportunities(signals: list[Signal]) -> list[Opportunity]:
    return [Opportunity(**candidate) for candidate in aggregate_candidates(signals) if candidate["priority"] is not None]


def aggregate_candidates(signals: list[Signal], now: datetime | None = None) -> list[dict]:
    """Aggregate every resolved company/molecule pair, including unqualified ones.

    Qualification remains controlled by ``priority``; retaining the candidate
    metadata allows later signals to rescore and promote the same pair without
    creating a duplicate opportunity.
    """
    # Group on the same normalized keys storage upserts on; grouping on display
    # strings split "Pfizer" and "Pfizer Inc" into rival scores for one row.
    grouped: dict[tuple[str, str], list[Signal]] = defaultdict(list)
    for signal in signals:
        if signal.company_name and signal.molecule_name:
            grouped[(normalize_company_name(signal.company_name), normalize_molecule_name(signal.molecule_name))].append(signal)

    output: list[dict] = []
    for group in grouped.values():
        company = Counter(s.company_name for s in group).most_common(1)[0][0]
        molecule = Counter(s.molecule_name for s in group).most_common(1)[0][0]
        unique = list({s.fingerprint: s for s in group}.values())
        score = score_signals(unique, now=now)
        signal_types = {s.signal_type for s in unique}
        priority = _priority(score, signal_types)

        needs = sorted({s.metadata_json.get("need_type", s.signal_type) for s in unique})
        roles: list[str] = []
        for signal_type in signal_types:
            for role in _ROLE_MAP.get(signal_type, []):
                if role not in roles:
                    roles.append(role)

        latest = max((s.event_date or s.discovered_at for s in unique), default=None)
        rationale = "; ".join(sorted({s.signal_type.replace("_", " ") for s in unique}))
        output.append({
            "company_name": company,
            "molecule_name": molecule,
            "score": score,
            "priority": priority,
            "likely_need_type": needs,
            "rationale": rationale,
            "decision_maker_role": roles[:3],
            "signal_fingerprints": [s.fingerprint for s in unique],
            "last_signal_at": latest,
        })
    return sorted(output, key=lambda item: item["score"], reverse=True)
