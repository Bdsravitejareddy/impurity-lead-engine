"""Pure helpers for safe legacy contact reconciliation.

The production repair job uses these functions to classify rows before any
write.  They deliberately return REVIEW for name-only matches so a common
name can never be merged just because punctuation or a degree suffix differs.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from impurity_leads.contacts.normalize import normalize_person_name, title_family


@dataclass(frozen=True)
class ContactMergeDecision:
    action: str
    reason: str
    survivor_id: str | None = None


def _same_route(left: dict[str, Any], right: dict[str, Any]) -> bool:
    left_route = str(left.get("profile_url") or "").rstrip("/").casefold()
    right_route = str(right.get("profile_url") or "").rstrip("/").casefold()
    return bool(left_route and right_route and left_route == right_route)


def _same_email(left: dict[str, Any], right: dict[str, Any]) -> bool:
    left_email = str(left.get("primary_email") or "").strip().casefold()
    right_email = str(right.get("primary_email") or "").strip().casefold()
    return bool(left_email and right_email and left_email == right_email)


def classify_contact_pair(left: dict[str, Any], right: dict[str, Any]) -> ContactMergeDecision:
    """Classify two rows without mutating them.

    Auto merge requires the same company and either an exact public route,
    exact email, or an exact normalized name plus compatible role context.
    """
    if left.get("merged_into_contact_id") or right.get("merged_into_contact_id"):
        return ContactMergeDecision("SKIP", "already_merged")
    if left.get("company_id") != right.get("company_id"):
        return ContactMergeDecision("REVIEW", "different_company")
    left_name = normalize_person_name(str(left.get("display_name") or left.get("normalized_name") or ""))
    right_name = normalize_person_name(str(right.get("display_name") or right.get("normalized_name") or ""))
    if not left_name or left_name != right_name:
        return ContactMergeDecision("REVIEW", "name_context_mismatch")
    if _same_route(left, right):
        return ContactMergeDecision("AUTO_MERGE", "same_profile_url")
    if _same_email(left, right):
        return ContactMergeDecision("AUTO_MERGE", "same_public_email")
    left_family = title_family(str(left.get("title") or left.get("department") or ""))
    right_family = title_family(str(right.get("title") or right.get("department") or ""))
    if left_family and left_family == right_family:
        return ContactMergeDecision("AUTO_MERGE", "exact_name_compatible_role")
    return ContactMergeDecision("REVIEW", "exact_name_without_independent_identity")


def choose_survivor(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Choose the richest canonical row deterministically."""
    def completeness(row: dict[str, Any]) -> tuple[int, int, str]:
        fields = ("title", "department", "profile_url", "primary_email", "primary_phone", "last_verified_at", "quality_diagnostics")
        filled = sum(bool(row.get(field)) for field in fields)
        score = float((row.get("quality_diagnostics") or {}).get("score") or 0) if isinstance(row.get("quality_diagnostics"), dict) else 0
        return filled, int(score), str(row.get("id") or "")

    return sorted(rows, key=completeness, reverse=True)[0]
