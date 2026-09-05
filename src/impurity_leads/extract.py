import re

_CAS_RE = re.compile(r"\b\d{2,7}-\d{2}-\d\b")
_QTY_RE = re.compile(r"\b\d+(?:\.\d+)?\s?(?:mg|g|kg)\b", re.I)


def extract_cas_numbers(text: str) -> list[str]:
    return list(dict.fromkeys(_CAS_RE.findall(text)))


def extract_quantities(text: str) -> list[str]:
    return list(dict.fromkeys(m.group(0).replace("  ", " ") for m in _QTY_RE.finditer(text)))


def extract_evidence_windows(text: str, phrases: list[str], window: int = 180) -> list[str]:
    lowered = text.lower()
    output: list[str] = []
    for phrase in phrases:
        start = 0
        needle = phrase.lower()
        while True:
            index = lowered.find(needle, start)
            if index < 0:
                break
            left = max(0, index - window)
            right = min(len(text), index + len(needle) + window)
            snippet = re.sub(r"\s+", " ", text[left:right]).strip()
            if snippet not in output:
                output.append(snippet)
            start = index + len(needle)
    return output
