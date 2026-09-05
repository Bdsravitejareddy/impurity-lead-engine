from pathlib import Path


def test_contact_tables_have_rls_no_anon_and_authenticated_read_only():
    sql = Path("supabase/schema.sql").read_text().lower()
    for table in ("contacts", "contact_evidence", "opportunity_contacts"):
        assert f"alter table public.{table} enable row level security" in sql
        assert f"revoke all on table public.{table} from anon" in sql
        assert f"grant select on table public.{table} to authenticated" in sql
        assert f"grant select, insert, update, delete on table public.{table} to service_role" in sql
    assert "raw_html" not in sql


def test_contact_schema_enforces_status_and_score_ranges():
    sql = Path("supabase/schema.sql").read_text().lower()
    assert "email_status" in sql and "pattern_confirmed" in sql and "verified_public" in sql
    assert "role_fit_score >= 0" in sql and "role_fit_score <= 100" in sql
    assert "contact_confidence >= 0" in sql and "contact_confidence <= 1" in sql
