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
_COMPANY_SUFFIX = re.compile(r"\b(incorporated|inc|limited|ltd|llc|plc|corp|corporation|co)\.?$", re.I)


def _clean(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().lower())


def normalize_company_name(name: str) -> str:
    value = re.sub(r"[,]+", "", _clean(name))
    value = _COMPANY_SUFFIX.sub("", value).strip(" .")
    return re.sub(r"\s+", " ", value)


def normalize_molecule_name(name: str) -> str:
    return _clean(name).strip(" ,.;:")


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
