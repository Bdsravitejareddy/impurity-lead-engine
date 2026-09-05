from impurity_leads.adapters.common_crawl import filter_index_records


def test_filters_to_relevant_same_domain_urls():
    records = [
        {"url": "https://example.com/careers/analytical-scientist"},
        {"url": "https://example.com/privacy"},
        {"url": "https://other.com/careers"},
    ]
    urls = filter_index_records(records, "example.com")
    assert urls == [{"url": "https://example.com/careers/analytical-scientist"}]


class FakeResponse:
    def __init__(self, *, json_data=None, text="", status_code=200):
        self._json = json_data
        self.text = text
        self.status_code = status_code
    def json(self):
        return self._json
    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


class FakeClient:
    def get(self, url, params=None, headers=None):
        if url.endswith("collinfo.json"):
            return FakeResponse(json_data=[{"id": "CC-MAIN-2026-30"}])
        return FakeResponse(text='{"url":"https://example.com/jobs/scientist"}\n{"url":"https://example.com/privacy"}\n')


def test_discover_uses_latest_index_and_filters_results():
    from impurity_leads.adapters.common_crawl import CommonCrawlAdapter
    adapter = CommonCrawlAdapter(client=FakeClient(), sleep_fn=lambda _: None)
    assert adapter.discover("example.com") == ["https://example.com/jobs/scientist"]
