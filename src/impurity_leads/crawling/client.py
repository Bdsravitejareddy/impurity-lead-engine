"""HTTP configuration for public crawling, independent of database clients."""

import httpx


def _reject_https_downgrade(response: httpx.Response) -> None:
    if response.has_redirect_location and response.url.scheme == "https":
        target = response.url.join(response.headers["location"])
        if target.scheme == "http":
            raise httpx.RequestError("HTTPS redirect downgrade blocked", request=response.request)


def create_crawl_client(timeout: float = 20.0) -> httpx.Client:
    return httpx.Client(
        timeout=timeout,
        follow_redirects=True,
        trust_env=False,
        event_hooks={"response": [_reject_https_downgrade]},
    )
