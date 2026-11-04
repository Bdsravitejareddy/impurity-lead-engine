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


def test_domain_prefix_is_removed_as_a_prefix_not_a_character_set():
    from impurity_leads.adapters.common_crawl import filter_index_records

    records = [{"url": "https://w.ockhardt.com/careers/impurity"}, {"url": "https://www.wockhardt.com/careers/impurity"}]
    # lstrip("www.") stripped characters, so "w.ockhardt.com" matched "wockhardt.com".
    assert [r["url"] for r in filter_index_records(records, "wockhardt.com", ("careers",))] == ["https://www.wockhardt.com/careers/impurity"]


class RecordingClient(FakeClient):
    def __init__(self):
        self.calls = []
    def get(self, url, params=None, headers=None):
        self.calls.append((url, params))
        return super().get(url, params, headers)


def test_cdx_query_is_bounded_html_only_and_collapsed():
    from impurity_leads.adapters.common_crawl import CDX_LIMIT, CommonCrawlAdapter
    client = RecordingClient()
    CommonCrawlAdapter(client=client, sleep_fn=lambda _: None).discover("example.com")
    params = client.calls[-1][1]
    assert params["limit"] == CDX_LIMIT
    assert params["collapse"] == "urlkey"
    assert params["filter"] == ["status:200", "mime:text/html"]


def test_collection_list_is_fetched_once_per_shared_cache():
    from impurity_leads.adapters.common_crawl import CommonCrawlAdapter, IndexNameCache
    client, cache, sleeps = RecordingClient(), IndexNameCache(), []
    for domain in ("example.com", "example.org"):
        CommonCrawlAdapter(client=client, sleep_fn=sleeps.append, index_cache=cache).discover(domain)
    assert [url for url, _ in client.calls].count("https://index.commoncrawl.org/collinfo.json") == 1
    assert cache.value == "CC-MAIN-2026-30" and sleeps == [1.0]
