from lxml import etree


def extract_sitemap_urls(xml: str) -> list[str]:
    root = etree.fromstring(xml.encode("utf-8"))
    values = root.xpath("//*[local-name()='loc']/text()")
    return [value.strip() for value in values if value.strip()]
