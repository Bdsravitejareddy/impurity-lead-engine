from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

EmailStatus = Literal["VERIFIED_PUBLIC", "PATTERN_CONFIRMED", "ROLE_ONLY", "STALE"]
PhoneStatus = Literal["VERIFIED_PUBLIC", "ROLE_ONLY", "STALE"]


class ContactEvidence(BaseModel):
    evidence_type: Literal["identity", "title", "email", "phone", "affiliation", "email_pattern"]
    observed_value: str
    source_type: str
    source_url: str
    evidence_text: str
    observed_at: datetime
    fingerprint: str
    metadata_json: dict[str, Any] = Field(default_factory=dict)

    @field_validator("evidence_text")
    @classmethod
    def cap_evidence(cls, value: str) -> str:
        return value[:800]


class ContactCandidate(BaseModel):
    company_name: str
    display_name: str
    normalized_name: str = ""
    title: str | None = None
    department: str | None = None
    profile_url: str | None = None
    primary_email: str | None = None
    email_status: EmailStatus = "ROLE_ONLY"
    primary_phone: str | None = None
    phone_status: PhoneStatus = "ROLE_ONLY"
    role_fit_score: int = Field(default=0, ge=0, le=100)
    contact_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    first_seen_at: datetime | None = None
    last_seen_at: datetime | None = None
    last_verified_at: datetime | None = None
    evidence: list[ContactEvidence] = Field(default_factory=list)


class RankedContact(BaseModel):
    contact: ContactCandidate
    rank: int = Field(ge=1, le=3)
    rationale: str
