import imaplib

from impurity_leads.tenders import parse_alert, run_tender_alerts

SINGLE = """Dear Seller,
A new bid matching your category has been published.

Bid Number: GEM/2026/B/6812345
Items: Impurity Reference Standards (Q3)
Quantity: 25
Ministry: Ministry of Health and Family Welfare
Department: Central Drugs Standard Control Organisation
Organisation: Central Drugs Laboratory
Bid Start Date: 20-11-2026 10:00 AM
Bid End Date: 05-12-2026 03:00 PM
View bid: https://bidplus.gem.gov.in/showbidDocument/8123456
"""

DIGEST = """New bids in your categories
GEM/2026/B/6800001
Item Category : Working Standards for HPLC
Total Quantity : 12
Bid End Date : 01-12-2026
https://bidplus.gem.gov.in/showbidDocument/8100001

GEM/2026/B/6800002
Item Category : Laboratory Glassware
Total Quantity : 300
Bid End Date : 03-12-2026
https://bidplus.gem.gov.in/showbidDocument/8100002
"""


def test_single_alert_gives_every_field():
    [bid] = parse_alert("New bid published", SINGLE)
    assert bid["bid_number"] == "GEM/2026/B/6812345"
    assert bid["items"] == "Impurity Reference Standards (Q3)"
    assert bid["quantity"] == "25"
    assert bid["organisation"] == "Central Drugs Laboratory"
    assert bid["department"] == "Central Drugs Standard Control Organisation"
    assert bid["start_date"] == "2026-11-20" and bid["end_date"] == "2026-12-05"
    assert bid["url"] == "https://bidplus.gem.gov.in/showbidDocument/8123456"
    assert bid["is_relevant"] is True


def test_digest_splits_into_bids_and_flags_only_standards():
    bids = {bid["bid_number"]: bid for bid in parse_alert("Bid digest", DIGEST)}
    assert set(bids) == {"GEM/2026/B/6800001", "GEM/2026/B/6800002"}
    assert bids["GEM/2026/B/6800001"]["items"] == "Working Standards for HPLC"
    assert bids["GEM/2026/B/6800001"]["url"].endswith("/8100001")
    assert bids["GEM/2026/B/6800001"]["is_relevant"] is True
    assert bids["GEM/2026/B/6800002"]["is_relevant"] is False
    assert bids["GEM/2026/B/6800002"]["end_date"] == "2026-12-03"


def test_emails_without_a_bid_number_are_ignored():
    assert parse_alert("Your GeM password was changed", "Hello, your password was changed.") == []


class Client:
    def __init__(self):
        self.rows = []

    def table(self, name):
        rows = self.rows

        class Table:
            def upsert(self, row, on_conflict=None):
                rows.append((name, row, on_conflict))
                return type("Q", (), {"execute": lambda self: None})()
        return Table()


def test_stage_is_off_without_an_inbox_and_stores_bids_when_set():
    assert run_tender_alerts(Client(), user="", password="")["status"] == "SKIPPED"
    client = Client()
    result = run_tender_alerts(client, user="u", password="p", fetch=lambda u, p, host: parse_alert("x", SINGLE))
    assert result == {"status": "COMPLETED", "bids": 1, "relevant": 1}
    assert client.rows[0][0] == "tenders" and client.rows[0][2] == "bid_number"


def test_login_failure_is_reported_without_details():
    def refuse(user, password, host):
        raise imaplib.IMAP4.error("AUTHENTICATIONFAILED secret-detail")
    assert run_tender_alerts(Client(), user="u", password="p", fetch=refuse) == {"status": "FAILED", "error": "error"}
