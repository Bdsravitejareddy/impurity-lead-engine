from types import SimpleNamespace

from impurity_leads.contact_targets import database_contact_targets, merge_contact_targets
from impurity_leads.models import Opportunity


class Query:
    def __init__(self, rows):
        self.rows = rows

    def select(self, *_):
        return self

    def gte(self, column, value):
        return Query([row for row in self.rows if row[column] >= value])

    def order(self, *_, **__):
        return self

    def range(self, start, end):
        return SimpleNamespace(execute=lambda: SimpleNamespace(data=self.rows[start:end + 1]))


class Client:
    def __init__(self, rows):
        self.rows = rows

    def table(self, name):
        return Query(self.rows)


ROWS = [
    {"score": 100, "priority": "HOT", "status": "new", "companies": {"legal_name": "Takeda", "merged_into_company_id": None}, "molecules": {"canonical_name": "IXAZOMIB"}},
    {"score": 80, "priority": "HIGH", "status": "dismissed", "companies": {"legal_name": "Cipla"}, "molecules": {"canonical_name": "LEDIPASVIR"}},
    {"score": 70, "priority": "HIGH", "status": "new", "companies": {"legal_name": "Old Co", "merged_into_company_id": "x"}, "molecules": {"canonical_name": "DRUG"}},
    {"score": 60, "priority": "REVIEW", "status": "new", "companies": {"legal_name": "Lupin"}, "molecules": {"canonical_name": "ZIPRASIDONE"}},
    {"score": 30, "priority": None, "status": "new", "companies": {"legal_name": "Low"}, "molecules": {"canonical_name": "X"}},
]


def test_database_targets_skip_dismissed_merged_and_low_scores():
    targets = database_contact_targets(Client(ROWS))
    assert [(t.company_name, t.molecule_name) for t in targets] == [("Takeda", "IXAZOMIB"), ("Lupin", "ZIPRASIDONE")]


def test_merge_keeps_this_runs_opportunities_and_dedupes_by_company_and_molecule():
    current = [Opportunity(company_name="Takeda", molecule_name="ixazomib", score=95, priority="HOT", rationale="this run")]
    stored = database_contact_targets(Client(ROWS))
    merged = merge_contact_targets(current, stored)
    assert [(m.company_name, m.molecule_name) for m in merged] == [("Takeda", "ixazomib"), ("Lupin", "ZIPRASIDONE")]
    assert merged[0].rationale == "this run"
