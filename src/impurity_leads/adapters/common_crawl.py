import json
import time
from urllib.parse import urlparse

from impurity_leads.crawling.client import create_crawl_client

DEFAULT_TERMS = (
    "career",
    "job",
    "pipeline",
    "research",
    "press",
    "news",
    "procurement",
    "tender",
    "impurity",
    "nitrosamine",
    "stability",
    "analytical",
)


def filter_index_records(
    records: list[dict],
    domain: str,
    url_terms: tuple[str, ...] = DEFAULT_TERMS,
) -> list[dict]:
    normalized_domain = domain.lower().lstrip("www.")
    output: list[dict] = []
    for record in records:
        url = record.get("url")
        if not url:
            continue
        parsed = urlparse(url)
        host = parsed.netloc.lower().lstrip("www.")
        if host != normalized_domain:
            continue
        haystack = f"{parsed.path}?{parsed.query}".lower()
        if not any(term in haystack for term in url_terms):
            continue
        output.append(record)
    return output


class CommonCrawlAdapter:
    collection_url = "https://index.commoncrawl.org/collinfo.json"
    index_root = "https://index.commoncrawl.org"

    def __init__(
        self,
        client=None,
        user_agent: str = "SVAK-Impurity-Lead-Research/0.1",
        max_urls_per_domain: int = 40,
        sleep_fn=time.sleep,
    ):
        self.client = client or create_crawl_client()
        self.user_agent = user_agent
        self.max_urls_per_domain = max_urls_per_domain
        self.sleep_fn = sleep_fn

    def latest_index_name(self) -> str:
        response = self.client.get(self.collection_url, headers={"User-Agent": self.user_agent})
        response.raise_for_status()
        collections = response.json() or []
        if not collections:
            raise RuntimeError("Common Crawl collection list is empty")
        return collections[0]["id"]

    def discover(self, domain: str, url_terms: tuple[str, ...] = DEFAULT_TERMS) -> list[str]:
        index_name = self.latest_index_name()
        self.sleep_fn(1.0)
        response = self.client.get(
            f"{self.index_root}/{index_name}-index",
            params={"url": f"{domain}/*", "output": "json", "filter": "status:200"},
            headers={"User-Agent": self.user_agent},
        )
        response.raise_for_status()
        records = [json.loads(line) for line in response.text.splitlines() if line.strip()]
        filtered = filter_index_records(records, domain, url_terms=url_terms)
        urls = list(dict.fromkeys(record["url"] for record in filtered))
        return urls[: self.max_urls_per_domain]
