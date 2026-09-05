import re

_COMPANY_SUFFIX = re.compile(r"\b(incorporated|inc|limited|ltd|llc|plc|corp|corporation|co)\.?$", re.I)


def _clean(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().lower())


def normalize_company_name(name: str) -> str:
    value = re.sub(r"[,]+", "", _clean(name))
    value = _COMPANY_SUFFIX.sub("", value).strip(" .")
    return re.sub(r"\s+", " ", value)


def normalize_molecule_name(name: str) -> str:
    return _clean(name).strip(" ,.;:")
