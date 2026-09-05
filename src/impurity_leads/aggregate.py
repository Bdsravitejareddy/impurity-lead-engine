from collections import defaultdict

from impurity_leads.models import Opportunity, Signal
from impurity_leads.score import score_signals

_ROLE_MAP = {
    "impurity_characterization": ["Head/Director Analytical R&D"],
    "degradation_product": ["Head/Director Analytical R&D"],
    "nitrosamine_ndsri": ["Analytical Development", "Quality", "Regulatory CMC"],
    "genotoxic_impurity": ["Analytical Development", "Regulatory CMC"],
    "reference_standard": ["Analytical R&D", "Strategic Sourcing/Procurement"],
    "direct_impurity_rfq": ["Analytical R&D", "Strategic Sourcing/Procurement"],
}


def _priority(score: int, signal_types: set[str]) -> str | None:
    if score >= 80 or "direct_impurity_rfq" in signal_types:
        return "HOT"
    if score >= 65:
        return "HIGH"
    if score >= 50:
        return "REVIEW"
    return None


def aggregate_opportunities(signals: list[Signal]) -> list[Opportunity]:
    grouped: dict[tuple[str, str], list[Signal]] = defaultdict(list)
    for signal in signals:
        if signal.company_name and signal.molecule_name:
            grouped[(signal.company_name, signal.molecule_name)].append(signal)

    output: list[Opportunity] = []
    for (company, molecule), group in grouped.items():
        unique = list({s.fingerprint: s for s in group}.values())
        score = score_signals(unique)
        signal_types = {s.signal_type for s in unique}
        priority = _priority(score, signal_types)
        if priority is None:
            continue

        needs = sorted({s.metadata_json.get("need_type", s.signal_type) for s in unique})
        roles: list[str] = []
        for signal_type in signal_types:
            for role in _ROLE_MAP.get(signal_type, []):
                if role not in roles:
                    roles.append(role)

        latest = max((s.event_date or s.discovered_at for s in unique), default=None)
        rationale = "; ".join(sorted({s.signal_type.replace("_", " ") for s in unique}))
        output.append(
            Opportunity(
                company_name=company,
                molecule_name=molecule,
                score=score,
                priority=priority,
                likely_need_type=needs,
                rationale=rationale,
                decision_maker_role=roles[:3],
                signal_fingerprints=[s.fingerprint for s in unique],
                last_signal_at=latest,
            )
        )
    return sorted(output, key=lambda item: item.score, reverse=True)
