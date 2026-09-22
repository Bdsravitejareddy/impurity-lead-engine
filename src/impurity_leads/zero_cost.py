"""Zero-cost provider policy and safe per-provider usage accounting.

The deterministic crawler uses public structured sources and public pages. Paid
search/model providers are opt-in capabilities and are blocked before any
network request when ``ZERO_COST_MODE`` is enabled.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from threading import Lock
from typing import Any


PAID_PROVIDERS = frozenset({
    "openai", "gemini", "groq", "tavily", "serper", "serpapi",
    "bing_search", "google_search", "brave_search", "paid_scraper",
})


@dataclass
class ProviderUsage:
    """Thread-safe counters safe to persist in run metrics and JSON logs."""

    _counts: dict[str, dict[str, int]] = field(default_factory=dict)
    _lock: Lock = field(default_factory=Lock, repr=False)

    def record(self, provider: str, *, requests: int = 0, jobs: int = 0,
               estimated_paid_requests: int = 0) -> None:
        name = str(provider).strip().lower() or "unknown"
        with self._lock:
            row = self._counts.setdefault(name, {"requests": 0, "jobs": 0, "estimated_paid_requests": 0})
            row["requests"] += max(0, int(requests))
            row["jobs"] += max(0, int(jobs))
            row["estimated_paid_requests"] += max(0, int(estimated_paid_requests))

    def rows(self) -> list[dict[str, Any]]:
        with self._lock:
            return [{"provider": provider, **values} for provider, values in sorted(self._counts.items())]


def paid_provider_disabled(provider: str, settings: Any, usage: ProviderUsage | None = None) -> RuntimeError:
    """Record and return the hard zero-cost policy error before a paid call."""
    if usage is not None:
        usage.record(provider, requests=1, estimated_paid_requests=1)
    return RuntimeError("paid_provider_disabled")


def assert_paid_provider_allowed(provider: str, settings: Any, usage: ProviderUsage | None = None) -> None:
    """Raise before network access when a paid provider is disabled by policy."""
    if bool(getattr(settings, "zero_cost_mode", False)):
        raise paid_provider_disabled(provider, settings, usage)


def provider_for_url(url: str) -> str:
    """Classify public request hosts for safe usage metrics only."""
    value = str(url).lower()
    if "europepmc.org" in value or "ebi.ac.uk/europepmc" in value:
        return "europe_pmc"
    if "api.fda.gov" in value or "fda.gov" in value:
        return "openfda"
    if "clinicaltrials.gov" in value:
        return "clinicaltrials_gov"
    if "commoncrawl.org" in value:
        return "common_crawl"
    if "patents.google.com" in value:
        return "google_patents"
    if "api.openai.com" in value:
        return "openai"
    return "public_web"
