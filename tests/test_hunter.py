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
