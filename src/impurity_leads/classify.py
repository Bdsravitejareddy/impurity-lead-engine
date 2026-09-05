from dataclasses import dataclass


@dataclass(frozen=True)
class Rule:
    signal_type: str
    phrases: tuple[str, ...]
    weight_with_molecule: int
    weight_without_molecule: int
    need_type: str


RULES = (
    Rule("direct_impurity_rfq", ("request for quotation", "rfq", "required impurity"), 70, 45, "custom impurity synthesis"),
    Rule("reference_standard", ("reference standard", "working standard"), 60, 25, "reference standard"),
    Rule("nitrosamine_ndsri", ("ndsri", "nitrosamine", "n-nitroso"), 45, 20, "nitrosamine/NDSRI"),
    Rule("genotoxic_impurity", ("genotoxic impurity", "ich m7"), 40, 18, "genotoxic impurity"),
    Rule("impurity_characterization", ("impurity characterization", "impurity isolation", "structure elucidation"), 38, 15, "impurity characterization"),
    Rule("degradation_product", ("degradation product", "degradation impurity"), 35, 15, "degradation impurity"),
    Rule("stability", ("forced degradation", "stability-indicating", "stability study"), 18, 8, "stability/degradation"),
    Rule("method_validation", ("method validation", "analytical method development"), 12, 5, "analytical development"),
)

_VENDOR_PHRASES = (
    "we manufacture impurity",
    "we manufacture and supply",
    "impurity standards supplier",
    "reference standards supplier",
    "custom impurity synthesis services",
    "catalogue of impurities",
)


def classify_signal(text: str, has_molecule: bool) -> list[tuple[str, int, str]]:
    lowered = text.lower()
    matches: list[tuple[str, int, str]] = []
    for rule in RULES:
        if any(phrase in lowered for phrase in rule.phrases):
            matches.append((
                rule.signal_type,
                rule.weight_with_molecule if has_molecule else rule.weight_without_molecule,
                rule.need_type,
            ))
    return matches


def looks_like_impurity_vendor(text: str) -> bool:
    lowered = text.lower()
    return any(phrase in lowered for phrase in _VENDOR_PHRASES)
