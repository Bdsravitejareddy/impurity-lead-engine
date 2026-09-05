from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class SourceRecord(BaseModel):
    source_name: str
    source_type: str
    source_record_id: str | None = None
    source_url: str
    published_at: datetime | None = None
    fetched_at: datetime
    company_name_raw: str | None = None
    company_domain_raw: str | None = None
    molecule_name_raw: str | None = None
    active_ingredient_raw: str | None = None
    signal_text: str
    country: str | None = None
    metadata_json: dict[str, Any] = Field(default_factory=dict)


class CompanyRef(BaseModel):
    normalized_name: str
    legal_name: str | None = None
    domain: str | None = None
    country: str | None = None
    company_type: str | None = None
    is_impurity_vendor: bool = False
    is_cro_cdmo: bool = False


class MoleculeRef(BaseModel):
    canonical_name: str
    synonyms: list[str] = Field(default_factory=list)
    cas_number: str | None = None
    unii: str | None = None
    development_code: str | None = None
    molecule_type: str | None = None
    small_molecule: bool | None = None


class Signal(BaseModel):
    company_name: str
    molecule_name: str | None = None
    source_type: str
    signal_type: str
    source_url: str
    source_record_id: str | None = None
    evidence_text: str
    event_date: datetime | None = None
    discovered_at: datetime
    freshness_days: int | None = None
    base_weight: int
    confidence: float = Field(ge=0.0, le=1.0)
    fingerprint: str
    metadata_json: dict[str, Any] = Field(default_factory=dict)


class Opportunity(BaseModel):
    company_name: str
    molecule_name: str
    score: int = Field(ge=0, le=100)
    priority: Literal["HOT", "HIGH", "REVIEW"]
    likely_need_type: list[str] = Field(default_factory=list)
    rationale: str
    decision_maker_role: list[str] = Field(default_factory=list)
    signal_fingerprints: list[str] = Field(default_factory=list)
    last_signal_at: datetime | None = None


class CrawlRunStats(BaseModel):
    source_adapter: str
    status: Literal["running", "success", "partial", "failed"]
    records_seen: int = 0
    records_inserted: int = 0
    errors: int = 0
    duration_seconds: float = 0.0
