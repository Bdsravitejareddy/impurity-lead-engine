from impurity_leads.targeted_research_jobs import queue_for_opportunity


class Table:
    def __init__(self): self.rows = []
    def upsert(self, row, **_): self.rows.append(row); return self
    def execute(self): return type("Result", (), {"data": self.rows})()
    def select(self, *_): return self
    def eq(self, *_): return self
    def limit(self, *_): return self


class Client:
    def __init__(self): self.tables = {"targeted_research_jobs": Table()}
    def table(self, name): return self.tables.setdefault(name, Table())


def test_queue_for_opportunity_is_idempotent_and_targeted():
    client = Client()
    opportunity = {"id": "o1", "company_name": "Cipla", "molecule_name": "Cobimetinib", "signal": "impurity", "score": 94}
    first = queue_for_opportunity(client, opportunity, [])
    second = queue_for_opportunity(client, opportunity, [])
    assert first["status"] == "TARGETED_SEARCH"
    assert second["status"] == "TARGETED_SEARCH"
    assert first["request"].target_dimension in {"PERSON_IDENTITY", "CURRENT_ROLE", "PROFESSIONAL_PROFILE"}
