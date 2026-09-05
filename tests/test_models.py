from datetime import datetime, timezone
import pytest
from pydantic import ValidationError

from impurity_leads.models import SourceRecord, Signal


def test_source_record_requires_source_url_and_signal_text():
    record = SourceRecord(
        source_name="fixture",
        source_type="job",
        source_record_id="job-1",
        source_url="https://example.com/jobs/1",
        fetched_at=datetime.now(timezone.utc),
        company_name_raw="Example Pharma",
        molecule_name_raw="Drug X",
        signal_text="characterization of degradation impurities",
    )
    assert record.source_type == "job"


def test_signal_confidence_is_bounded():
    with pytest.raises(ValidationError):
        Signal(
            company_name="Example Pharma",
            molecule_name="Drug X",
            source_type="job",
            signal_type="impurity_characterization",
            source_url="https://example.com/jobs/1",
            evidence_text="degradation impurities",
            discovered_at=datetime.now(timezone.utc),
            base_weight=38,
            confidence=1.2,
            fingerprint="abc",
        )
