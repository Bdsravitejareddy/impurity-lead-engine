import zlib
from dataclasses import dataclass
from datetime import datetime, timezone

from dateutil.parser import isoparse
from lxml import etree

# The sitemap protocol caps an uncompressed sitemap at 50 MB.
MAX_SITEMAP_BYTES = 50 * 1024 * 1024
_PARSER = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=False)


@dataclass(frozen=True)
class Sitemap:
    is_index: bool
    entries: tuple[tuple[str, datetime | None], ...]

    def locations(self) -> list[str]:
        """Newest lastmod first; undated entries follow in document order."""
        floor = datetime.min.replace(tzinfo=timezone.utc)
        ordered = sorted(self.entries, key=lambda entry: entry[1] or floor, reverse=True)
        return [location for location, _ in ordered]


def _lastmod(value: str | None) -> datetime | None:
    try:
        parsed = isoparse(value.strip()) if value else None
    except (ValueError, OverflowError):
        return None
    if parsed and parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _decompress(content: bytes, max_bytes: int) -> bytes:
    if not content.startswith(b"\x1f\x8b"):
        return content
    decompressor = zlib.decompressobj(16 + zlib.MAX_WBITS)
    data = decompressor.decompress(content, max_bytes)
    if decompressor.unconsumed_tail:
        raise ValueError("sitemap_too_large")
    return data


def parse_sitemap(content: str | bytes, max_bytes: int = MAX_SITEMAP_BYTES) -> Sitemap:
    """Parse a urlset or sitemap index, gzipped (``.xml.gz``) or plain."""
    data = content.encode("utf-8") if isinstance(content, str) else _decompress(content, max_bytes)
    root = etree.fromstring(data, _PARSER)
    is_index = etree.QName(root).localname == "sitemapindex"
    entries = []
    for node in root.xpath("./*[local-name()='sitemap' or local-name()='url']"):
        location = "".join(node.xpath("./*[local-name()='loc']/text()")).strip()
        if location:
            entries.append((location, _lastmod("".join(node.xpath("./*[local-name()='lastmod']/text()")))))
    return Sitemap(is_index=is_index, entries=tuple(entries))


def extract_sitemap_urls(xml: str) -> list[str]:
    return parse_sitemap(xml).locations()
