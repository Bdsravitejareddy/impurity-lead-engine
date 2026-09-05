import time
from email.utils import parsedate_to_datetime
from typing import Protocol

import httpx

from impurity_leads.crawling.client import create_crawl_client


class RobotsLike(Protocol):
    def can_fetch(self, url: str) -> bool: ...


class HttpFetcher:
    def __init__(
        self,
        client=None,
        robots_policy: RobotsLike | None = None,
        user_agent: str = "SVAK-Impurity-Lead-Research/0.1",
        max_retries: int = 2,
        sleep_fn=time.sleep,
    ):
        self.client = client or create_crawl_client()
        self.robots_policy = robots_policy
        self.user_agent = user_agent
        self.max_retries = max_retries
        self.sleep_fn = sleep_fn

    def _retry_delay(self, response, attempt: int) -> float:
        value = response.headers.get("Retry-After") if hasattr(response, "headers") else None
        if value:
            if value.isdigit():
                return min(float(value), 60.0)
            try:
                dt = parsedate_to_datetime(value)
                return max(0.0, min((dt.timestamp() - time.time()), 60.0))
            except (TypeError, ValueError, OverflowError):
                pass
        return min(2 ** attempt, 8)

    def fetch(self, url: str) -> str | None:
        if self.robots_policy and not self.robots_policy.can_fetch(url):
            return None
        for attempt in range(self.max_retries + 1):
            try:
                response = self.client.get(url, headers={"User-Agent": self.user_agent})
            except (httpx.HTTPError, OSError):
                if attempt >= self.max_retries:
                    return None
                self.sleep_fn(min(2 ** attempt, 8))
                continue

            status = getattr(response, "status_code", 200)
            if status == 429 or 500 <= status <= 599:
                if attempt >= self.max_retries:
                    return None
                self.sleep_fn(self._retry_delay(response, attempt))
                continue
            if status in {401, 403} or status >= 400:
                return None
            return response.text
        return None
