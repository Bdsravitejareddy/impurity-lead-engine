from datetime import datetime, timezone
from types import SimpleNamespace

from impurity_leads.seed_sources import (
    database_seeds, discover_missing_domains, domain_candidates, load_run_seeds, verify_domain,
)
from impurity_leads.seeds import CompanySeed


class FakeQuery:
    def __init__(self, table, rows):
        self.table, self.rows = table, rows

    def select(self, *_):
        return self

    def order(self, *_ , **__):
        return self

    def gte(self, column, value):
        return FakeQuery(self.table, [row for row in self.rows if (row.get(column) or 0) >= value])

    def range(self, start, end):
        return SimpleNamespace(execute=lambda: SimpleNamespace(data=self.rows[start:end + 1]))


class FakeClient:
    def __init__(self, tables):
        self.tables = tables
        self.updates = []

    def table(self, name):
        client = self
        query = FakeQuery(name, self.tables.get(name, []))

        def update(values):
            return SimpleNamespace(eq=lambda column, value: SimpleNamespace(execute=lambda: client.updates.append((name, value, values))))
        query.update = update
        return query


COMPANIES = [
    {"id": "takeda", "legal_name": "Takeda Pharmaceuticals U.S.A., Inc.", "domain": "takeda.com"},
    {"id": "takeda-dup", "legal_name": "Takeda", "domain": None, "merged_into_company_id": "takeda"},
    {"id": "sandoz", "legal_name": "SANDOZ", "domain": None},
    {"id": "lupin", "legal_name": "LUPIN", "domain": "www.lupin.com"},
]
OPPORTUNITIES = [
    {"company_id": "takeda", "score": 100, "status": "new", "molecules": {"canonical_name": "IXAZOMIB CITRATE"}},
    {"company_id": "takeda-dup", "score": 60, "status": "new", "molecules": {"canonical_name": "Vonoprazan"}},
    {"company_id": "sandoz", "score": 56, "status": "new", "molecules": {"canonical_name": "TOBRAMYCIN"}},
    {"company_id": "lupin", "score": 80, "status": "dismissed", "molecules": {"canonical_name": "FOSPHENYTOIN"}},
    {"company_id": "lupin", "score": 40, "status": "new", "molecules": {"canonical_name": "Ziprasidone"}},
]


def test_database_seeds_use_survivors_and_skip_unqualified_rows():
    seeds = database_seeds(FakeClient({"companies": COMPANIES, "opportunities": OPPORTUNITIES}))
    # The merged Takeda row's molecule joins its survivor; Sandoz has no website
    # yet; Lupin's only qualified opportunity is dismissed.
    assert seeds == [CompanySeed("Takeda Pharmaceuticals U.S.A., Inc.", "takeda.com", ["IXAZOMIB CITRATE", "Vonoprazan"])]


def test_run_seeds_merge_the_csv_override_and_survive_a_database_failure(tmp_path):
    (tmp_path / "seeds").mkdir()
    (tmp_path / "seeds/companies.csv").write_text("company_name,domain,molecules\nTakeda,takeda.com,Pioglitazone\nIndoco,indoco.com,alogliptin\n")
    client = FakeClient({"companies": COMPANIES, "opportunities": OPPORTUNITIES})
    seeds = load_run_seeds(None, tmp_path, client_factory=lambda: client)
    assert [(seed.domain, seed.molecules) for seed in seeds] == [
        ("indoco.com", ["alogliptin"]),
        ("takeda.com", ["Pioglitazone", "IXAZOMIB CITRATE", "Vonoprazan"]),
    ]

    def broken():
        raise RuntimeError("database down")
    assert [seed.domain for seed in load_run_seeds(None, tmp_path, client_factory=broken)] == ["indoco.com", "takeda.com"]


def test_domain_candidates_skip_common_words():
    assert domain_candidates("SANDOZ")[:2] == ["sandoz.com", "sandozpharma.com"]
    assert domain_candidates("NX Development Corp.") == []
    assert "intracellulartherapies.com" in domain_candidates("Intra-Cellular Therapies, Inc.")


class FakeHttp:
    def __init__(self, pages):
        self.pages = pages

    def get(self, url, headers=None):
        if url.endswith("/robots.txt"):
            return SimpleNamespace(status_code=404, text="")
        status, final_url, html = self.pages[url]
        return SimpleNamespace(status_code=status, url=final_url, text=html)


def test_verify_domain_requires_name_host_and_industry_evidence():
    pharma = "<title>Sandoz | Generic medicines</title><p>Pharmaceutical products for patients</p>"
    assert verify_domain(FakeHttp({"https://sandoz.com/": (200, "https://www.sandoz.com/", pharma)}), "sandoz.com", "SANDOZ", "ua") == "sandoz.com"
    parked = "<title>torrent.com - pharmaceutical domains for sale</title>"
    assert verify_domain(FakeHttp({"https://torrent.com/": (200, "https://ww16.torrent.com/", parked)}), "torrent.com", "Torrent Pharmaceuticals", "ua") is None
    unrelated = "<title>Aveo GmbH - Holiday apartments</title>"
    assert verify_domain(FakeHttp({"https://aveo.de/": (200, "https://aveo.de/", unrelated)}), "aveo.de", "Aveo Pharmaceuticals, Inc.", "ua") is None
    partial = "<title>Intra Systems - drug delivery</title>"
    assert verify_domain(FakeHttp({"https://intra.com/": (200, "https://intra.com/", partial)}), "intra.com", "Intra-Cellular Therapies, Inc.", "ua") is None


def test_discovery_stores_verified_websites_and_records_every_check():
    now = datetime(2026, 11, 5, tzinfo=timezone.utc)
    companies = [*COMPANIES, {"id": "prasco", "legal_name": "Prasco LLC", "domain": None, "domain_checked_at": "2026-11-01T00:00:00+00:00"}]
    opportunities = [*OPPORTUNITIES, {"company_id": "prasco", "score": 78, "status": "new", "molecules": {"canonical_name": "Estradiol"}}]
    client = FakeClient({"companies": companies, "opportunities": opportunities})
    http = FakeHttp({"https://sandoz.com/": (200, "https://www.sandoz.com/", "<title>Sandoz</title> generic medicines")})
    result = discover_missing_domains(None, client=client, http=http, now=now, pause=0, resolves=lambda host: host == "sandoz.com")
    # Prasco was checked four days ago, so it waits for the 30-day recheck.
    assert result["found"] == [{"company": "SANDOZ", "domain": "sandoz.com"}]
    assert client.updates == [("companies", "sandoz", {"domain_checked_at": now.isoformat(), "domain": "sandoz.com", "domain_source": "AUTO_DISCOVERED"})]
