"""Government demand: GeM bid alert emails turned into a tender list.

GeM (the Government e-Marketplace) emails registered sellers about new bids in
their categories. Those alerts are the legitimate, free route to tender data:
GeM has no public feed, and its portal search is not open to automated access.

This stage reads the alerts from the inbox they arrive in (IMAP, read-only),
pulls each bid's number, items, quantity, buyer, dates and link, and stores
them in ``public.tenders`` for the dashboard's Demand page. Bids that name an
impurity, reference or working standard, or a nitrosamine, are flagged.

Off unless GEM_ALERT_IMAP_USER and GEM_ALERT_IMAP_PASSWORD are set. Nothing is
sent, deleted or marked read: messages are fetched with BODY.PEEK.
"""
from __future__ import annotations

import email
import imaplib
import os
import re
from datetime import datetime, timedelta, timezone
from email.header import decode_header, make_header
from email.utils import parsedate_to_datetime
from typing import Any

from bs4 import BeautifulSoup
from dateutil.parser import parse as parse_date

BID_NUMBER = re.compile(r"\bGEM/\d{4}/[A-Z]/\d{5,}\b", re.I)
BID_LINK = re.compile(r"https?://bidplus\.gem\.gov\.in/[^\s\"'<>]+", re.I)
RELEVANT = re.compile(r"impurit|reference standard|working standard|nitrosamin|ndsri|pharmacopoei|"
                      r"certified reference|crm\b|analytical standard|related substance", re.I)
# "Label: value" lines in an alert, by the names GeM uses or might use.
FIELDS = {
    "items": r"items?|item\s*category|product|category|bid\s*title",
    "quantity": r"quantity|total\s*quantity|qty",
    "ministry": r"ministry|ministry/state\s*name|state",
    "department": r"department|department\s*name",
    "organisation": r"organi[sz]ation|organi[sz]ation\s*name|buyer|office",
    "location": r"location|consignee\s*address|delivery\s*location|city",
    "start_date": r"start\s*date|bid\s*start\s*date|published\s*on|bid\s*start",
    "end_date": r"end\s*date|bid\s*end\s*date|closing\s*date|bid\s*end|due\s*date",
}
DEFAULT_LOOKBACK_DAYS = 14


def _text(message: email.message.Message) -> str:
    """Plain text of an email, from its text part or its HTML part."""
    parts = message.walk() if message.is_multipart() else [message]
    plain, html = [], []
    for part in parts:
        kind = part.get_content_type()
        if part.get_content_maintype() == "multipart" or part.get("Content-Disposition", "").startswith("attachment"):
            continue
        payload = part.get_payload(decode=True) or b""
        text = payload.decode(part.get_content_charset() or "utf-8", errors="replace")
        (plain if kind == "text/plain" else html if kind == "text/html" else []).append(text)
    if plain:
        return "\n".join(plain)
    return "\n".join(BeautifulSoup(chunk, "lxml").get_text("\n") for chunk in html)


def _date(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return parse_date(value, dayfirst=True, fuzzy=True).date().isoformat()
    except (ValueError, OverflowError):
        return None


def _field(block: str, pattern: str) -> str | None:
    match = re.search(rf"(?im)^\s*(?:{pattern})\s*[:\-–]\s*(.+?)\s*$", block)
    return re.sub(r"\s+", " ", match.group(1)).strip()[:500] if match else None


def parse_alert(subject: str, body: str, received_at: datetime | None = None) -> list[dict[str, Any]]:
    """Every bid in one alert email. Alerts can list several bids; each block
    runs from one bid number to the next."""
    text = body.replace("\r", "")
    positions = [match.start() for match in BID_NUMBER.finditer(text)]
    if not positions:
        return []
    links = BID_LINK.findall(text)
    tenders: dict[str, dict[str, Any]] = {}
    for index, start in enumerate(positions):
        # Labels may sit just above the bid number, so take a little context before it.
        block = text[max(0, start - 300 if index == 0 else start): positions[index + 1] if index + 1 < len(positions) else len(text)]
        number = BID_NUMBER.search(text[start:]).group(0).upper()
        if number in tenders:
            continue
        values = {name: _field(block, pattern) for name, pattern in FIELDS.items()}
        link = next((url for url in BID_LINK.findall(block)), None) or (links[index] if index < len(links) else None)
        items = values["items"] or (subject.strip()[:300] if len(positions) == 1 else None)
        tenders[number] = {
            "bid_number": number,
            "items": items,
            "quantity": values["quantity"],
            "ministry": values["ministry"],
            "department": values["department"],
            "organisation": values["organisation"],
            "location": values["location"],
            "start_date": _date(values["start_date"]),
            "end_date": _date(values["end_date"]),
            "url": link or "https://bidplus.gem.gov.in/all-bids",
            "source": "gem_email_alert",
            "is_relevant": bool(RELEVANT.search(f"{items or ''} {block}")),
            "excerpt": re.sub(r"\s+", " ", block).strip()[:1500],
            "received_at": (received_at or datetime.now(timezone.utc)).isoformat(),
        }
    return list(tenders.values())


def fetch_alerts(user: str, password: str, *, host: str = "imap.gmail.com", sender: str = "gem.gov.in",
                 since_days: int = DEFAULT_LOOKBACK_DAYS) -> list[dict[str, Any]]:
    """Parse GeM alerts from the last ``since_days`` days, read-only."""
    since = (datetime.now(timezone.utc) - timedelta(days=since_days)).strftime("%d-%b-%Y")
    tenders: list[dict[str, Any]] = []
    with imaplib.IMAP4_SSL(host) as mailbox:
        mailbox.login(user, password)
        # readonly=True: nothing is marked read, moved or deleted.
        mailbox.select("INBOX", readonly=True)
        _, data = mailbox.search(None, "FROM", f'"{sender}"', "SINCE", since)
        for message_id in (data[0] or b"").split():
            _, parts = mailbox.fetch(message_id, "(BODY.PEEK[])")
            raw = next((part[1] for part in parts if isinstance(part, tuple)), None)
            if not raw:
                continue
            message = email.message_from_bytes(raw)
            subject = str(make_header(decode_header(message.get("Subject", ""))))
            try:
                received = parsedate_to_datetime(message.get("Date"))
            except (TypeError, ValueError):
                received = None
            tenders.extend(parse_alert(subject, _text(message), received))
    return tenders


def run_tender_alerts(client, *, user: str | None = None, password: str | None = None,
                      fetch=fetch_alerts) -> dict[str, Any]:
    user = user if user is not None else os.environ.get("GEM_ALERT_IMAP_USER", "")
    password = password if password is not None else os.environ.get("GEM_ALERT_IMAP_PASSWORD", "")
    if not (user and password):
        return {"status": "SKIPPED", "reason": "gem_alert_inbox_not_configured"}
    try:
        tenders = fetch(user, password, host=os.environ.get("GEM_ALERT_IMAP_HOST", "imap.gmail.com"))
    except (imaplib.IMAP4.error, OSError) as error:
        # Never echo credentials; the class name says enough (login refused, network).
        return {"status": "FAILED", "error": type(error).__name__}
    for tender in tenders:
        client.table("tenders").upsert(tender, on_conflict="bid_number").execute()
    return {"status": "COMPLETED", "bids": len(tenders), "relevant": sum(t["is_relevant"] for t in tenders)}
