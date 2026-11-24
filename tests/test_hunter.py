from datetime import datetime, timezone
from types import SimpleNamespace

import httpx

from impurity_leads.hunter import contact_confidence, hunter_people, run_hunter_people

NOW = datetime(2026, 11, 22, tzinfo=timezone.utc)
PAYLOAD = {"data": {"emails": [
    {"value": "quality.head@example.com", "type": "personal", "confidence": 92, "first_name": "Asha", "last_name": "Rao",
     "position": "Head of Quality Control", "department": "management"},
    {"value": "info@example.com", "type": "generic", "confidence": 99, "position": None},
    {"value": "sales@example.com", "type": "personal", "confidence": 80, "first_name": "Sam", "last_name": "Lee", "position": "Sales Manager"},
    {"value": "cmc@example.com", "type": "personal", "confidence": 70, "first_name": "Ravi", "last_name": "Kumar", "position": "Director, CMC Analytical Development"},
]}}


def test_hunter_keeps_only_personal_role_relevant_addresses_and_lowercases_them():
    http = SimpleNamespace(get=lambda url, params=None: httpx.Response(200, json=PAYLOAD, request=httpx.Request("GET", url)))
    people = hunter_people(http, "k", "example.com")
    assert [p["email"] for p in people] == ["quality.head@example.com", "cmc@example.com"]


def test_hunter_confidence_is_capped_so_it_never_reads_as_verified():
    assert contact_confidence(100) == 0.6
    assert contact_confidence(50) == 0.3


class FakeTable:
    def __init__(self, store, name):
        self.store, self.name = store, name

    def upsert(self, row, on_conflict=None):
        self.store.append((self.name, "upsert", row))
        return SimpleNamespace(execute=lambda: SimpleNamespace(data=[{"id": f"contact-{len(self.store)}"}]))

    def update(self, values):
        return SimpleNamespace(eq=lambda column, value: SimpleNamespace(execute=lambda: self.store.append((self.name, "update", values, value))))


class FakeClient:
    def __init__(self, companies, opportunities):
        self.store = []
        self.companies, self.opportunities = companies, opportunities

    def table(self, name):
        if name == "companies" and not self.store:
            pass
        return FakeTable(self.store, name)


def test_stage_is_skipped_without_a_key_and_never_calls_hunter():
    calls = []
    http = SimpleNamespace(get=lambda *a, **k: calls.append(a))
    result = run_hunter_people(None, None, http=http, api_key="")
    assert result["status"] == "SKIPPED" and calls == []


def test_stage_searches_one_company_and_stores_role_only_contacts(monkeypatch):
    import impurity_leads.hunter as hunter
    companies = {"c1": {"id": "c1", "legal_name": "Example Pharma", "domain": "example.com", "people_checked_at": None}}
    monkeypatch.setattr(hunter, "qualified_companies", lambda client, columns: companies)
    client = FakeClient(companies, [])
    http = SimpleNamespace(get=lambda url, params=None: httpx.Response(200, json=PAYLOAD, request=httpx.Request("GET", url)), close=lambda: None)
    result = run_hunter_people(None, client, http=http, api_key="k", max_searches=1, now=NOW)
    assert result["searched"] == 1 and result["contacts_upserted"] == 2
    contact_rows = [row for name, op, row, *_ in client.store if name == "contacts" and op == "upsert"]
    assert {row["email_status"] for row in contact_rows} == {"ROLE_ONLY"}
    assert all(row["contact_confidence"] <= 0.6 for row in contact_rows)
    source_rows = [row for name, op, row, *_ in client.store if name == "contact_sources"]
    assert source_rows and all(row["source_type"] == "HUNTER_DOMAIN_SEARCH" and row["evidence_strength"] == "THIRD_PARTY_DATABASE" for row in source_rows)


def _http(routes):
    """Fake client answering by URL; routes map a URL to (status, json)."""
    calls = []

    def get(url, params=None):
        calls.append(url)
        status, body = routes[url]
        return httpx.Response(status, json=body, request=httpx.Request("GET", url))
    return SimpleNamespace(get=get, close=lambda: None, calls=calls)


def test_allowance_is_spread_over_the_days_until_it_resets():
    from datetime import date
    from impurity_leads.hunter import searches_for_today
    account = {"data": {"requests": {"searches": {"used": 10, "available": 50}}, "reset_date": "2026-12-01"}}
    # 40 left over 7 days -> 6 a day, capped at 5 per run.
    assert searches_for_today(account, today=date(2026, 11, 24), cap=5) == (5, 40)
    account["data"]["requests"]["searches"]["used"] = 48
    assert searches_for_today(account, today=date(2026, 11, 24), cap=5) == (1, 2)
    account["data"]["requests"]["searches"]["used"] = 50
    assert searches_for_today(account, today=date(2026, 11, 24), cap=5) == (0, 0)


def test_used_up_allowance_skips_hunter_and_leaves_free_sources(monkeypatch):
    import impurity_leads.hunter as hunter
    monkeypatch.setattr(hunter, "qualified_companies", lambda client, columns: {})
    http = _http({hunter.ACCOUNT_URL: (200, {"data": {"requests": {"searches": {"used": 50, "available": 50}}, "reset_date": "2026-12-01"}})})
    result = run_hunter_people(None, FakeClient({}, []), http=http, api_key="k", now=NOW)
    assert result["status"] == "QUOTA_EXHAUSTED" and result["fallback"] == "free_sources_only"
    assert http.calls == [hunter.ACCOUNT_URL]


def test_429_stops_the_stage_without_failing_it(monkeypatch):
    import impurity_leads.hunter as hunter
    companies = {f"c{i}": {"id": f"c{i}", "legal_name": f"Pharma {i}", "domain": f"p{i}.com", "people_checked_at": None} for i in range(3)}
    monkeypatch.setattr(hunter, "qualified_companies", lambda client, columns: companies)
    http = _http({hunter.ACCOUNT_URL: (500, {}), hunter.HUNTER_URL: (429, {"errors": [{"details": "usage limit"}]})})
    result = run_hunter_people(None, FakeClient(companies, []), http=http, api_key="k", max_searches=3, now=NOW)
    assert result["status"] == "QUOTA_EXHAUSTED" and result["searched"] == 0
    assert http.calls.count(hunter.HUNTER_URL) == 1


def test_hunter_pattern_is_stored_on_the_company(monkeypatch):
    import impurity_leads.hunter as hunter
    companies = {"c1": {"id": "c1", "legal_name": "Example Pharma", "domain": "example.com", "people_checked_at": None}}
    monkeypatch.setattr(hunter, "qualified_companies", lambda client, columns: companies)
    payload = {"data": {**PAYLOAD["data"], "pattern": "{f}{last}"}}
    client = FakeClient(companies, [])
    http = _http({hunter.ACCOUNT_URL: (200, {}), hunter.HUNTER_URL: (200, payload)})
    result = run_hunter_people(None, client, http=http, api_key="k", max_searches=1, now=NOW)
    assert result["patterns_found"] == 1
    [update] = [row for name, op, row, *_ in client.store if name == "companies" and op == "update"]
    assert update["email_pattern"] == "flast" and update["email_pattern_source"] == "hunter"


class FallbackClient:
    """Contacts table for the pattern fallback, recording writes."""

    def __init__(self, contacts):
        self.contacts, self.writes = contacts, []

    def table(self, name):
        client = self

        class Query:
            def select(self, columns):
                return self

            def in_(self, column, values):
                self.rows = [row for row in client.contacts if row[column] in values]
                return self

            def update(self, values):
                return SimpleNamespace(eq=lambda column, value: SimpleNamespace(
                    execute=lambda: client.writes.append((name, "update", values, value))))

            def upsert(self, row, on_conflict=None):
                return SimpleNamespace(execute=lambda: client.writes.append((name, "upsert", row)))

            def execute(self):
                return SimpleNamespace(data=self.rows)
        return Query()


def test_fallback_prefers_a_pattern_published_on_the_company_site(monkeypatch):
    import impurity_leads.hunter as hunter
    from impurity_leads.hunter import run_pattern_fallback
    companies = {"c1": {"id": "c1", "domain": "example.com", "email_pattern": "flast", "email_pattern_source": "hunter"}}
    monkeypatch.setattr(hunter, "qualified_companies", lambda client, columns: companies)
    client = FallbackClient([
        {"id": "a", "company_id": "c1", "display_name": "Asha Rao", "primary_email": "asha.rao@example.com", "email_status": "VERIFIED_PUBLIC"},
        {"id": "b", "company_id": "c1", "display_name": "Ravi Kumar", "primary_email": "ravi.kumar@example.com", "email_status": "VERIFIED_PUBLIC"},
        {"id": "c", "company_id": "c1", "display_name": "Neha Shah", "primary_email": None, "email_status": "ROLE_ONLY"},
    ])
    result = run_pattern_fallback(client, now=NOW)
    assert result["emails_built"] == 1 and result["public_patterns"] == 1
    [(_, _, values, contact_id)] = [w for w in client.writes if w[0] == "contacts"]
    assert contact_id == "c" and values["primary_email"] == "neha.shah@example.com"
    assert values["email_status"] == "PATTERN_CONFIRMED"


def test_fallback_uses_hunter_pattern_at_lower_confidence_and_never_overwrites(monkeypatch):
    import impurity_leads.hunter as hunter
    from impurity_leads.hunter import run_pattern_fallback
    companies = {"c1": {"id": "c1", "domain": "www.example.com", "email_pattern": "flast", "email_pattern_source": "hunter"},
                 "c2": {"id": "c2", "domain": "other.com", "email_pattern": None}}
    monkeypatch.setattr(hunter, "qualified_companies", lambda client, columns: companies)
    client = FallbackClient([
        {"id": "c", "company_id": "c1", "display_name": "Neha Shah", "primary_email": None, "email_status": "ROLE_ONLY"},
        {"id": "d", "company_id": "c1", "display_name": "Sam Lee", "primary_email": "sam@example.com", "email_status": "ROLE_ONLY"},
        {"id": "e", "company_id": "c2", "display_name": "No Pattern", "primary_email": None, "email_status": "ROLE_ONLY"},
    ])
    result = run_pattern_fallback(client, now=NOW)
    updates = [w for w in client.writes if w[0] == "contacts"]
    assert [(w[3], w[2]["primary_email"], w[2]["email_status"]) for w in updates] == [("c", "nshah@example.com", "ROLE_ONLY")]
    assert updates[0][2]["contact_confidence"] < 0.5
    assert result["hunter_patterns"] == 1
