"""Observable orchestration for bounded post-crawl stages."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Iterable


@dataclass(frozen=True)
class StageResult:
    name: str
    status: str
    processed: int = 0
    sources: int = 0
    claims: int = 0
    links: int = 0
    metrics: dict[str, Any] = None
    error: str | None = None

    def __post_init__(self):
        if self.metrics is None:
            object.__setattr__(self, "metrics", {})


@dataclass(frozen=True)
class PostCrawlResult:
    status: str
    stages: tuple[StageResult, ...]


def _stage_result(name: str, payload: dict[str, Any]) -> StageResult:
    status = str(payload.get("status") or "COMPLETED").upper()
    return StageResult(
        name=name,
        status=status,
        processed=int(payload.get("processed", payload.get("selected", 0)) or 0),
        sources=int(payload.get("sources", payload.get("sources_used", 0)) or 0),
        claims=int(payload.get("claims", payload.get("new_claims", 0)) or 0),
        links=int(payload.get("links", payload.get("opportunity_links", 0)) or 0),
        metrics=dict(payload),
    )


def run_post_crawl_stages(stages: Iterable[tuple[str, Callable[[], dict[str, Any]]]]) -> PostCrawlResult:
    """Run every optional stage, preserving later stages after a failure."""
    results: list[StageResult] = []
    for name, operation in stages:
        try:
            results.append(_stage_result(name, operation()))
        except Exception as exc:
            results.append(StageResult(name=name, status="FAILED", error=type(exc).__name__, metrics={"error": str(exc)[:240]}))
    status = "FAILED" if results and all(item.status == "FAILED" for item in results) else "PARTIAL" if any(item.status == "FAILED" for item in results) else "COMPLETED"
    return PostCrawlResult(status=status, stages=tuple(results))
