"""The SQL company key and soft merge against disposable PostgreSQL."""
from pathlib import Path
import re

from impurity_leads.normalize import COMPANY_SUFFIXES, normalize_company_name
from impurity_leads.storage.supabase_store import _stable_uuid, company_alias_map

MIGRATIONS = Path("supabase/migrations")
NAMES = [
    "Takeda Pharmaceuticals U.S.A., Inc.", "takeda pharmaceuticals u.s.a.", "Novo Nordisk A/S", "NOVO NORDISK INC",
    "Boehringer Ingelheim Pharma GmbH & Co. KG", "Dr. Reddy's Laboratories Pvt. Ltd.", "Hoffmann-La Roche",
    "Merck KGaA", "Merck & Co., Inc.", "Pharma AG", "Société Générale S.A.", "Sanofi_Pasteur SA", "  ", "Lonza Holdings",
]


def _apply(db):
    for name in ("20261104110000_company_soft_merge.sql", "20261104130000_company_normalization.sql"):
        db.execute((MIGRATIONS / name).read_text())


def test_sql_suffix_list_matches_python():
    sql = (MIGRATIONS / "20261104130000_company_normalization.sql").read_text()
    assert tuple(re.search(r"\\s\+\(([^)]*)\)\$", sql).group(1).split("|")) == COMPANY_SUFFIXES


def test_sql_company_key_matches_python(db):
    _apply(db)
    for name in NAMES:
        assert db.execute("select public.company_normalization_key(%s)", (name,)).fetchone()[0] == normalize_company_name(name), name


def test_migration_soft_merges_rows_that_now_share_a_key(db):
    _apply(db)
    rows = [
        ("takeda pharmaceuticals u.s.a.", "Takeda Pharmaceuticals U.S.A., Inc.", "takeda.com"),
        ("takeda", "Takeda", None),
        ("bayer", "Bayer", None),
        ("bayer ag", "Bayer AG", None),
        ("unique co", "Unique Co", None),
    ]
    for normalized, legal, domain in rows:
        db.execute("insert into public.companies(id, normalized_name, legal_name, domain) values (%s, %s, %s, %s)",
                   (str(_stable_uuid("company", normalized)), normalized, legal, domain))
    db.execute("insert into public.contacts(id, company_id, normalized_name, display_name) values (%s, %s, 'a b', 'A B')",
               (str(_stable_uuid("contact", "x")), str(_stable_uuid("company", "bayer ag"))))
    _apply(db)  # re-running is a no-op
    merged = dict(db.execute("select normalized_name, (select normalized_name from public.companies s where s.id = c.merged_into_company_id) from public.companies c").fetchall())
    assert merged == {"takeda pharmaceuticals u.s.a.": None, "takeda": "takeda pharmaceuticals u.s.a.",
                      "bayer": "bayer ag", "bayer ag": None, "unique co": None}
    audit = db.execute(Path("supabase/audits/company_normalization_audit.sql").read_text()).fetchall()
    assert audit and all(row[2] == 1 for row in audit)
    stored = [dict(zip(("id", "normalized_name", "legal_name", "merged_into_company_id"), map(lambda v: str(v) if v else v, row)))
              for row in db.execute("select id, normalized_name, legal_name, merged_into_company_id from public.companies")]
    aliases = company_alias_map(stored)
    assert aliases["takeda"] == (str(_stable_uuid("company", "takeda pharmaceuticals u.s.a.")), "takeda pharmaceuticals u.s.a.")
    assert aliases["bayer"] == (str(_stable_uuid("company", "bayer ag")), "bayer ag")
