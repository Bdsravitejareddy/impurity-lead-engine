"""Company announcements: press releases and news posts on the company's own site.

An announcement is a dated, first-party statement of what a company is doing
now: an approval, a filing, a launch, a new facility, an inspection result or a
recall. It is context for a lead (why now), not proof of impurity demand, so it
scores as a capped context signal. Impurity wording inside a release is still
picked up by the normal classifier.

Press releases also name people: executives quoted in the release and media
contacts. ``announcement_people`` reads those so the contact crawl can store
them with the release as current-role evidence.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from urllib.parse import urlparse

from bs4 import BeautifulSoup
from dateutil.parser import isoparse, parse as parse_date

NEWS_PATH = re.compile(r"/(news|press|media|newsroom|press-releases?|announcements?|stories|updates)(/|-|$)", re.I)

# Most specific first; a release can carry several.
EVENT_TYPES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("recall_or_warning", re.compile(r"\brecall|warning letter|form 483|import alert|official action indicated|\bOAI\b", re.I)),
    ("approval", re.compile(r"\b(final|tentative)?\s*approval\b|\bapproved\b|\breceives?\b.{0,30}\b(nod|clearance)\b|\bdesignation\b", re.I)),
    ("filing", re.compile(r"\b(filed|files|submitted|submits|submission)\b.{0,60}\b(anda|nda|bla|dmf|maa|ind|dossier|application)\b|\b(anda|nda|dmf)\b.{0,40}\b(filed|submitted|accepted)\b", re.I)),
    ("launch", re.compile(r"\blaunch(es|ed)?\b|\bintroduces?\b.{0,40}\b(generic|tablets|capsules|injection)", re.I)),
    ("inspection", re.compile(r"\binspection\b|\bEIR\b|establishment inspection report|zero observations", re.I)),
    ("facility", re.compile(r"\b(new|expand\w*|commission\w*|inaugurat\w*)\b.{0,60}\b(facility|plant|site|capacity|unit|block)\b", re.I)),
    ("deal", re.compile(r"\b(acquire[sd]?|acquisition|partnership|licens(e|ing) agreement|collaboration|in-licens\w*|divest\w*)\b", re.I)),
    ("clinical", re.compile(r"\bphase\s*(1|2|3|i{1,3})\b|\btopline\b|\bclinical (trial|study)\b", re.I)),
)

# '..., said Dr. Jane Smith, Chief Scientific Officer at Example.'
_QUOTE_AFTER = re.compile(
    r"\b(?:said|says|stated|commented|added|noted)\s+"
    r"(?P<name>(?:Dr\.?\s+)?[A-Z][A-Za-z'’.-]+(?:\s+[A-Z][A-Za-z'’.-]+){1,3}),\s+"
    r"(?P<title>[^.\"“”]{3,120}?)(?=[.\"“”]|\s+(?:at|of)\s+[A-Z])"
)
# 'Jane Smith, Chief Scientific Officer, said ...'
_QUOTE_BEFORE = re.compile(
    r"(?P<name>(?:Dr\.?\s+)?[A-Z][A-Za-z'’.-]+(?:\s+[A-Z][A-Za-z'’.-]+){1,3}),\s+"
    r"(?P<title>[^,.\"“”]{3,100}),\s+(?:said|says|stated|commented|added)\b"
)
_MEDIA_CONTACT = re.compile(r"(media|press|investor)\s+(contact|enquiries|inquiries|relations)", re.I)
_EMAIL = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.I)
_NAME_LINE = re.compile(r"^(?:Dr\.?\s+)?[A-Z][A-Za-z'’.-]+(?:\s+[A-Z][A-Za-z'’.-]+){1,3}$")
_TITLE_WORDS = re.compile(
    r"chief|officer|president|director|head|vice|vp|manager|founder|chairman|chairperson|ceo|cfo|coo|cso|cto|"
    r"scientist|lead|partner|general counsel|communications|relations|spokes",
    re.I,
)
# Words that look like a capitalised name but are not one.
_NOT_A_NAME = re.compile(r"^(the|this|our|we|it|company|management|according)\b", re.I)
# Headings and boilerplate that sit next to a media-contact block.
_NOT_NAME_WORDS = {
    "press", "release", "releases", "media", "contact", "contacts", "investor", "investors", "relations", "news",
    "statement", "harbor", "harbour", "safe", "about", "company", "limited", "ltd", "inc", "pharma", "pharmaceuticals",
    "corporate", "communications", "for", "further", "information", "please", "read", "more", "share", "follow",
}


def _looks_like_person(name: str) -> bool:
    words = re.sub(r"^Dr\.?\s+", "", name).split()
    return 2 <= len(words) <= 4 and not any(word.lower().strip(".,") in _NOT_NAME_WORDS for word in words)


def _email_for(name: str, email: str | None) -> str | None:
    """Keep an address only when its local part carries the person's own name."""
    if not email:
        return None
    local = re.sub(r"[^a-z]", "", email.split("@", 1)[0].lower())
    words = [re.sub(r"[^a-z]", "", word.lower()) for word in re.sub(r"^Dr\.?\s+", "", name).split()]
    first, last = words[0], words[-1]
    if (len(first) >= 3 and first in local) or (len(last) >= 3 and last in local):
        return email
    return None


_MONTHS = r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?"
_VISIBLE_DATE = re.compile(rf"\b(?:\d{{1,2}}(?:st|nd|rd|th)?\s+{_MONTHS},?\s+\d{{4}}|{_MONTHS}\s+\d{{1,2}}(?:st|nd|rd|th)?,?\s+\d{{4}})\b")


def _jsonld_date(soup: BeautifulSoup) -> datetime | None:
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        found = re.search(r'"datePublished"\s*:\s*"([^"]+)"', script.string or script.get_text() or "")
        if found:
            try:
                value = isoparse(found.group(1))
                return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
            except (ValueError, OverflowError):
                continue
    return None


def release_date(soup: BeautifulSoup, text: str) -> datetime | None:
    """Publication date from JSON-LD, else the first date written near the top of the release."""
    found = _jsonld_date(soup)
    if found:
        return found
    match = _VISIBLE_DATE.search(text[:1500])
    if not match:
        return None
    try:
        return parse_date(match.group(0)).replace(tzinfo=timezone.utc)
    except (ValueError, OverflowError):
        return None


@dataclass
class Announcement:
    url: str
    title: str
    published_at: datetime
    event_types: list[str]
    text: str
    people: list[dict] = field(default_factory=list)

    @property
    def summary(self) -> str:
        return f"{self.title}. {self.text[:400]}"


def is_news_url(url: str) -> bool:
    return bool(NEWS_PATH.search(urlparse(url).path or ""))


def event_types(text: str) -> list[str]:
    return [kind for kind, pattern in EVENT_TYPES if pattern.search(text)]


def _clean(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip(" ,;:-–—")


def announcement_people(text: str) -> list[dict]:
    """People quoted in a release, and named media contacts with their address."""
    people: dict[str, dict] = {}

    def add(name: str, title: str | None, email: str | None = None, kind: str = "quoted"):
        name = _clean(name)
        title = _clean(title) if title else None
        if title:
            # 'Head – CSR, Lupin' -> 'Head – CSR': drop segments that are not role words.
            parts = [part for part in (_clean(part) for part in title.split(",")) if part]
            kept = [part for part in parts if _TITLE_WORDS.search(part)]
            # No role words at all: a capitalised phrase that is not a person.
            if not kept:
                return
            title = ", ".join(kept)
        if _NOT_A_NAME.match(name) or not _looks_like_person(name):
            return
        email = _email_for(name, email)
        current = people.setdefault(name, {"name": name, "title": None, "email": None, "kind": kind})
        current["title"] = current["title"] or title
        current["email"] = current["email"] or email

    for pattern in (_QUOTE_AFTER, _QUOTE_BEFORE):
        for match in pattern.finditer(text):
            add(match.group("name"), match.group("title"))
    # Media contact blocks: a name line, optional title line, then an address.
    for match in _MEDIA_CONTACT.finditer(text):
        block = text[match.end(): match.end() + 400]
        lines = [line for line in (_clean(part) for part in re.split(r"[\n|•]| {2,}", block)) if line]
        email = next((found.group(0).lower() for found in map(_EMAIL.search, lines) if found), None)
        for index, line in enumerate(lines[:4]):
            candidate = re.sub(r"^[:\s]+", "", line)
            if _NAME_LINE.match(candidate) and not _TITLE_WORDS.search(candidate):
                title = lines[index + 1] if index + 1 < len(lines) and _TITLE_WORDS.search(lines[index + 1]) else "Media contact"
                add(candidate, title if _TITLE_WORDS.search(title) else "Media relations", email, kind="media_contact")
                break
    return list(people.values())


def parse_announcement(url: str, html: str, published_at: datetime | None) -> Announcement | None:
    """A dated news or press page as an announcement; None for listing pages and undated pages."""
    if not is_news_url(url):
        return None
    soup = BeautifulSoup(html, "lxml")
    published_at = _jsonld_date(soup) or published_at
    heading = soup.find("h1") or soup.find("meta", attrs={"property": "og:title"})
    title = heading.get("content") if heading is not None and heading.name == "meta" else (heading.get_text(" ", strip=True) if heading else "")
    if not title:
        return None
    for node in soup(["script", "style", "noscript", "nav", "header", "footer", "aside"]):
        node.decompose()
    body = soup.find("article") or soup.find("main") or soup.body or soup
    text = body.get_text("\n", strip=True)
    # A listing page links many items and has little prose of its own.
    if len(text) < 300:
        return None
    flat = re.sub(r"\s+", " ", text)
    published_at = published_at or release_date(soup, flat)
    if published_at is None:
        return None
    return Announcement(url=url, title=_clean(title)[:250], published_at=published_at,
                        # The headline's own event leads; body mentions follow.
                        event_types=list(dict.fromkeys([*event_types(title), *event_types(flat)])), text=flat[:4000],
                        people=announcement_people(text))
