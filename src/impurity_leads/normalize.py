import re

# Trial comparators such as "Placebo", "Matching placebo" or "Vehicle Cream" are
# listed as DRUG interventions but are not products anyone sources impurities for.
_INACTIVE_COMPARATOR = re.compile(r"\b(placebo|vehicle|sham|dummy)\b", re.I)
_PARENTHETICAL = re.compile(r"\([^)]*\)|\[[^\]]*\]")
_DOSE = re.compile(r"\b\d+(?:[.,]\d+)?\s*(?:mg/kg|mg/m2|mg|mcg|µg|ug|g|ml|iu|units?|%)(?=\W|$).*$", re.I)
_QUALIFIER = re.compile(r"\b(?:high|low|medium|mid|standard|reduced|fixed)[\s-]dose\b|\bcombination therapy\b|\bmonotherapy\b|\bopen[\s-]label\b|\b(?:long[\s-]term )?extension\b", re.I)
_DOSAGE_FORM = re.compile(r"\s+(?:for\s+)?(?:injection|infusion|tablets?|capsules?|cream|ointment|gel|oral solution|solution|suspension|patch)$", re.I)
# Regimens and care descriptions are recorded as DRUG interventions but name no molecule.
_NON_MOLECULE = re.compile(r"\b(?:chemotherapy|standard of care|best supportive care|usual care|investigator'?s choice)\b", re.I)
# Biologics registered as DRUG interventions: antibodies (-mab), fusion proteins
# (-cept), peptides (-tide), growth factors, cell and gene therapies, insulins.
# Their makers do not buy small-molecule impurity standards.
_BIOLOGIC = re.compile(
    r"\w(?:mab|cept|tide|grastim|poetin|cel|vec)\b|\b(?:insulin|vaccine|antibod(?:y|ies)|\w*globulin|peptides?|cells?)\b",
    re.I,
)
# Sponsor development codes: "BAY 94-8862", "LY3298176", "EX-101".
_DEVELOPMENT_CODE = re.compile(r"^[a-z]{1,6}[- ]?\d[\w-]*(?: \d[\w-]*)?$", re.I)
_PLAIN_NAME = re.compile(r"^[a-z][a-z -]*$", re.I)
# Legal forms and group words that differ between the records naming one
# company ("Takeda", "Takeda Pharmaceuticals U.S.A., Inc."). They are stripped
# after punctuation, repeatedly, and never from a one-word name. KGaA stays:
# Merck KGaA and Merck & Co. are different companies.
# supabase/migrations/20261104130000_company_normalization.sql mirrors this list.
COMPANY_SUFFIXES = (
    "incorporated", "inc", "limited", "ltd", "llc", "llp", "lp", "plc", "corporation", "corp", "co",
    "ag", "gmbh", "kg", "sa", "nv", "bv", "se", "kk", "pvt", "private", "spa", "srl", "ab", "a s",
    "holdings", "holding", "usa", "us", "pharmaceuticals", "pharmaceutical", "pharma",
)
_COMPANY_SUFFIX = re.compile(r"\s+(?:" + "|".join(COMPANY_SUFFIXES) + r")$")


def _clean(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().lower())


def normalize_company_name(name: str) -> str:
    # "U.S.A." -> "usa", "Reddy's" -> "reddys", "A/S" -> "a s", "Hoffmann-La" -> "hoffmann la".
    value = re.sub(r"[.'\u2019]", "", (name or "").lower())
    value = re.sub(r"[\W_]+", " ", value).strip()
    while True:
        stripped = _COMPANY_SUFFIX.sub("", value)
        if stripped == value:
            return value
        value = stripped


def normalize_molecule_name(name: str) -> str:
    return _clean(name).strip(" ,.;:")


def is_obvious_biologic(name: str) -> bool:
    return bool(_BIOLOGIC.search(name or ""))


def is_development_code(name: str) -> bool:
    return bool(_DEVELOPMENT_CODE.match((name or "").strip()))


def nonproprietary_name(other_names: list[str]) -> str | None:
    """Pick the name to use for a coded intervention from its other names.

    ClinicalTrials.gov lists INNs in lower case and brands capitalised, so a
    lower-case plain name wins, then any plain name; codes are never chosen.
    """
    plain = [name for name in other_names if _PLAIN_NAME.match(name) and not is_development_code(name)]
    return next((name for name in plain if name == name.lower()), plain[0] if plain else None)


def is_inactive_comparator(name: str) -> bool:
    return bool(_INACTIVE_COMPARATOR.search(name or ""))


def clean_intervention_names(name: str) -> list[str]:
    """Turn a trial intervention label into molecule names.

    "Abrocitinib 100 mg" -> ["Abrocitinib"]; "lopinavir/ritonavir (LPV/r) with
    NRTIs" -> ["lopinavir", "ritonavir"]; regimens and comparators -> [].
    """
    value = _PARENTHETICAL.sub(" ", name or "")
    value = re.split(r"\s+(?:with|plus|in combination with|followed by)\s+", value, maxsplit=1, flags=re.I)[0]
    names: list[str] = []
    for part in re.split(r"\s*(?:/|\+|,|;| and )\s*", value):
        part = _QUALIFIER.sub(" ", _DOSE.sub("", part))
        part = _DOSAGE_FORM.sub("", re.sub(r"\s+", " ", part).strip(" -,.;:"))
        if len(part) < 3 or is_inactive_comparator(part) or _NON_MOLECULE.search(part):
            continue
        if part.casefold() not in {existing.casefold() for existing in names}:
            names.append(part)
    return names
