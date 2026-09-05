from urllib.parse import urlparse

_TOKEN_WEIGHTS = {
    "leadership": 150,
    "management": 95,
    "team": 90,
    "people": 90,
    "research": 80,
    "science": 80,
    "analytical": 85,
    "development": 70,
    "quality": 70,
    "regulatory": 70,
    "procurement": 85,
    "sourcing": 85,
    "contact": 60,
    "press": 50,
    "news": 45,
    "investor": 50,
    "about": 40,
    "r-and-d": 80,
    "rd": 60,
}


def _normalized_domain(value: str) -> str:
    return value.casefold().strip().removeprefix("www.")


def contact_candidate_urls(urls: list[str], domain: str, limit: int = 12) -> list[str]:
    wanted_domain = _normalized_domain(domain)
    scored: dict[str, tuple[int, int, str]] = {}
    for position, url in enumerate(urls):
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or _normalized_domain(parsed.netloc) != wanted_domain:
            continue
        path = parsed.path.casefold()
        score = sum(weight for token, weight in _TOKEN_WEIGHTS.items() if token in path)
        if score <= 0:
            continue
        canonical = f"{wanted_domain}{parsed.path.rstrip('/') or '/'}"
        current = scored.get(canonical)
        item = (score, position, url)
        if current is None or score > current[0]:
            scored[canonical] = item
    ordered = sorted(scored.values(), key=lambda item: (-item[0], item[1]))
    return [url for _, _, url in ordered[: max(0, limit)]]
