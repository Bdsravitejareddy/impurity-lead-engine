from impurity_leads.crawling.fetch import HttpFetcher


class DenyPolicy:
    def can_fetch(self, url: str) -> bool:
        return False


class ExplodingClient:
    def get(self, url: str, headers=None):
        raise AssertionError("HTTP request should not happen when robots denies access")


def test_fetcher_does_not_request_disallowed_url():
    fetcher = HttpFetcher(client=ExplodingClient(), robots_policy=DenyPolicy(), user_agent="crawler")
    assert fetcher.fetch("https://example.com/private") is None
