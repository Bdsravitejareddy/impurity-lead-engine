from datetime import datetime, timezone
from pathlib import Path

from impurity_leads.models import Opportunity, Signal
from impurity_leads.storage.supabase_store import SupabaseLeadStore


class FakeTable:
    def __init__(self):
        self.rows = []
    def upsert(self, row, **kwargs):
        self.rows.append((row, kwargs))
        return self
    def execute(self):
        return type("Result", (), {"data": [row for row, _ in self.rows]})()


class FakeClient:
    def __init__(self):
        self.tables = {}
    def table(self, name):
        self.tables.setdefault(name, FakeTable())
        return self.tables[name]


def test_store_writes_structured_signal_without_raw_html():
    now = datetime.now(timezone.utc)
    client = FakeClient()
    store = SupabaseLeadStore(client)
    signal = Signal(
        company_name="Example Pharma",
        molecule_name="Drug X",
        source_type="job",
        signal_type="impurity_characterization",
        source_url="https://example.com/jobs/1",
        evidence_text="compact evidence",
        discovered_at=now,
        base_weight=38,
        confidence=1.0,
        fingerprint="abc",
    )
    store.save_signal(signal)
    row = client.tables["signals"].rows[0][0]
    assert row["fingerprint"] == "abc"
    assert row["evidence_text"] == "compact evidence"
    assert "html" not in row


def test_store_links_opportunity_to_signal_fingerprint():
    client = FakeClient()
    store = SupabaseLeadStore(client)
    opportunity = Opportunity(
        company_name="Example Pharma",
        molecule_name="Drug X",
        score=80,
        priority="HOT",
        likely_need_type=["impurity characterization"],
        rationale="impurity characterization",
        decision_maker_role=["Head/Director Analytical R&D"],
        signal_fingerprints=["abc"],
    )
    store.save_opportunity(opportunity)
    assert client.tables["opportunity_signals"].rows


def test_store_retains_unqualified_company_molecule_candidate():
    client = FakeClient()
    store = SupabaseLeadStore(client)
    store.save_candidate({"company_name": "Example Pharma", "molecule_name": "Drug X", "score": 36,
                          "rationale": "regulatory application", "signal_fingerprints": ["sig-1"]})
    row = client.tables["company_molecules"].rows[0][0]
    assert row["candidate_status"] == "UNQUALIFIED"
    assert row["candidate_score"] == 36
    assert row["candidate_signal_fingerprints"] == ["sig-1"]


def test_schema_enables_rls_and_revokes_anon_access():
    sql = Path("supabase/schema.sql").read_text().lower()
    for table in ["companies", "molecules", "company_molecules", "signals", "opportunities", "opportunity_signals", "crawl_runs", "crawl_domains"]:
        assert f"alter table public.{table} enable row level security" in sql
    assert "revoke all on table public.signals from anon" in sql
    assert "grant select on table public.opportunities to authenticated" in sql

from impurity_leads.contacts.models import ContactCandidate, ContactEvidence, RankedContact


def _ranked_contact(now):
    evidence = ContactEvidence(
        evidence_type="email",
        observed_value="jane.smith@example.com",
        source_type="company_site",
        source_url="https://example.com/team",
        evidence_text="Jane Smith Director Analytical Development jane.smith@example.com",
        observed_at=now,
        fingerprint="contact-email-fp",
    )
    contact = ContactCandidate(
        company_name="Example Pharma",
        display_name="Jane Smith",
        normalized_name="jane smith",
        title="Director, Analytical Development",
        department="analytical",
        profile_url="https://example.com/people/jane",
        primary_email="jane.smith@example.com",
        email_status="VERIFIED_PUBLIC",
        role_fit_score=85,
        contact_confidence=1.0,
        first_seen_at=now,
        last_seen_at=now,
        last_verified_at=now,
        evidence=[evidence],
    )
    return RankedContact(contact=contact, rank=1, rationale="target analytical leader")


def test_store_writes_contact_evidence_without_raw_html():
    now = datetime.now(timezone.utc)
    client = FakeClient()
    store = SupabaseLeadStore(client)
    ranked = _ranked_contact(now)
    store.save_contact("Example Pharma", ranked)
    contact_row = client.tables["contacts"].rows[0][0]
    evidence_row = client.tables["contact_evidence"].rows[0][0]
    assert contact_row["normalized_name"] == "jane smith"
    assert contact_row["email_status"] == "VERIFIED_PUBLIC"
    assert evidence_row["fingerprint"] == "contact-email-fp"
    assert "raw_html" not in contact_row
    assert "raw_html" not in evidence_row
    assert "html" not in evidence_row


def test_store_links_contact_to_opportunity():
    now = datetime.now(timezone.utc)
    client = FakeClient()
    store = SupabaseLeadStore(client)
    opportunity = Opportunity(
        company_name="Example Pharma",
        molecule_name="Drug X",
        score=90,
        priority="HOT",
        likely_need_type=["nitrosamine/NDSRI"],
        rationale="x",
    )
    ranked = _ranked_contact(now)
    store.link_opportunity_contact(opportunity, ranked)
    row = client.tables["opportunity_contacts"].rows[0][0]
    assert row["rank"] == 1
    assert row["rationale"] == "target analytical leader"


def test_store_reuses_existing_canonical_contact_for_academic_suffix_variant():
    class SelectableTable(FakeTable):
        def __init__(self, name):
            super().__init__()
            self.name = name
        def select(self, *_): return self
        def eq(self, *_): return self
        def execute(self):
            if self.name == "contacts":
                return type("Result", (), {"data": [{"id": "canonical", "normalized_name": "benjamin roembke", "display_name": "Benjamin Roembke, Ph.D.", "title": "Director, Quality", "department": "quality", "profile_url": None, "primary_email": None}]})()
            return super().execute()

    class SelectableClient(FakeClient):
        def table(self, name):
            self.tables.setdefault(name, SelectableTable(name))
            return self.tables[name]

    now = datetime.now(timezone.utc)
    client = SelectableClient(); store = SupabaseLeadStore(client)
    ranked = _ranked_contact(now)
    ranked.contact.display_name = "Benjamin Roembke PhD"
    ranked.contact.title = "Director, Quality"
    ranked.contact.normalized_name = "benjamin roembke"
    store.save_contact("Teva Pharmaceuticals", ranked)
    assert client.tables["contacts"].rows[0][0]["id"] == "canonical"
