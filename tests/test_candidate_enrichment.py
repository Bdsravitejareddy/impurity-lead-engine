from datetime import datetime, timezone

from impurity_leads.candidate_enrichment import enrich_candidate
from impurity_leads.models import Signal, SourceRecord
from impurity_leads.storage.supabase_store import _stable_uuid


class _Result:
    def __init__(self, data):
        self.data = data


class _Table:
    def __init__(self, client, name):
        self.client, self.name, self.filters = client, name, []

    def select(self, *_):
        return self

    def eq(self, key, value):
        self.filters.append((key, value))
        return self

    def upsert(self, row, on_conflict=None, **_):
        rows = self.client.tables.setdefault(self.name, [])
        keys = (on_conflict or "id").split(",")
        existing = next((item for item in rows if all(item.get(key) == row.get(key) for key in keys)), None)
        if existing:
            existing.update(row)
        else:
            rows.append(dict(row))
        return self

    def execute(self):
        rows = self.client.tables.setdefault(self.name, [])
        data = [row for row in rows if all(row.get(key) == value for key, value in self.filters)]
        self.filters = []
        return _Result(data)


class _Client:
    def __init__(self, rows):
        self.tables = rows

    def table(self, name):
        return _Table(self, name)


def _seed_client():
    company_id = str(_stable_uuid("company", "sandoz"))
    molecule_id = str(_stable_uuid("molecule", "tobramycin"))
    signals = []
    for fingerprint, url in (("reg-1", "https://api.fda.gov/a"), ("reg-2", "https://api.fda.gov/b")):
        signal = Signal(
            company_name="SANDOZ", molecule_name="TOBRAMYCIN", source_type="regulatory",
            signal_type="regulatory_application", source_url=url, evidence_text="FDA application",
            discovered_at=datetime.now(timezone.utc), base_weight=22, confidence=1.0, fingerprint=fingerprint,
        )
        signals.append({"id": str(_stable_uuid("signal", fingerprint)), "company_id": company_id, "molecule_id": molecule_id,
                        **signal.model_dump(mode="json")})
    candidate_id = str(_stable_uuid("company-molecule", f"{company_id}:{molecule_id}"))
    rows = {
        "companies": [{"id": company_id, "normalized_name": "sandoz", "legal_name": "SANDOZ"}],
        "molecules": [{"id": molecule_id, "canonical_name": "TOBRAMYCIN"}],
        "company_molecules": [{"id": candidate_id, "company_id": company_id, "molecule_id": molecule_id,
                                "candidate_score": 44, "candidate_status": "UNQUALIFIED"}],
        "signals": signals,
        "opportunities": [], "opportunity_signals": [],
    }
    return _Client(rows), company_id, molecule_id


def _technical_record():
    return SourceRecord(
        source_name="PubMed", source_type="publication", source_record_id="18486398",
        source_url="https://pubmed.ncbi.nlm.nih.gov/18486398/", fetched_at=datetime.now(timezone.utc),
        company_name_raw="SANDOZ", molecule_name_raw="TOBRAMYCIN",
        signal_text="Identification of tobramycin impurities for quality control process monitoring; impurity characterization.",
    )


def test_real_candidate_is_rescored_and_promoted_once_from_persisted_evidence():
    client, company_id, molecule_id = _seed_client()
    first = enrich_candidate(client, company_id=company_id, molecule_id=molecule_id,
                             company_name="SANDOZ", molecule_name="TOBRAMYCIN", records=[_technical_record()])
    assert first["before_score"] == 44
    assert first["after_score"] >= 50
    assert first["promoted"] is True
    assert first["new_signals"] == 1
    assert len(client.tables["opportunities"]) == 1

    second = enrich_candidate(client, company_id=company_id, molecule_id=molecule_id,
                              company_name="SANDOZ", molecule_name="TOBRAMYCIN", records=[_technical_record()])
    assert second["new_signals"] == 0
    assert second["duplicate_signals_prevented"] == 1
    assert len(client.tables["signals"]) == 3
    assert len(client.tables["opportunities"]) == 1


def test_generic_molecule_text_without_a_signal_does_not_change_candidate():
    client, company_id, molecule_id = _seed_client()
    generic = SourceRecord(
        source_name="Public reference", source_type="publication", source_url="https://example.org/tobramycin",
        fetched_at=datetime.now(timezone.utc), company_name_raw="SANDOZ", molecule_name_raw="TOBRAMYCIN",
        signal_text="Tobramycin is an aminoglycoside antibiotic.",
    )
    result = enrich_candidate(client, company_id=company_id, molecule_id=molecule_id,
                              company_name="SANDOZ", molecule_name="TOBRAMYCIN", records=[generic])
    assert result["new_signals"] == 0
    assert result["after_score"] == 44
    assert result["promoted"] is False
