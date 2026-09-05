import csv
from datetime import datetime, timezone
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Font

from impurity_leads.contacts.models import RankedContact
from impurity_leads.models import Opportunity

_BASE_HEADERS = [
    "Date",
    "Priority",
    "Score",
    "Company",
    "Molecule/API",
    "Likely Need",
    "Why Now",
    "Recommended Role 1",
    "Recommended Role 2",
    "Signal Count",
    "Last Seen",
]

_CONTACT_FIELDS = [
    "Name",
    "Title",
    "Department",
    "Role Fit",
    "Email",
    "Email Status",
    "Phone",
    "Phone Status",
    "Confidence",
    "Profile URL",
    "Last Verified",
    "Evidence URLs",
]

_HEADERS = _BASE_HEADERS + [
    f"Contact {index} {field}"
    for index in range(1, 4)
    for field in _CONTACT_FIELDS
]


def _contact_values(ranked: RankedContact | None) -> list[str | int | float]:
    if ranked is None:
        return [""] * len(_CONTACT_FIELDS)
    contact = ranked.contact
    evidence_urls = list(dict.fromkeys(item.source_url for item in contact.evidence if item.source_url))
    return [
        contact.display_name,
        contact.title or "",
        contact.department or "",
        contact.role_fit_score,
        contact.primary_email or "",
        contact.email_status,
        contact.primary_phone or "",
        contact.phone_status,
        contact.contact_confidence,
        contact.profile_url or "",
        contact.last_verified_at.isoformat() if contact.last_verified_at else "",
        "; ".join(evidence_urls),
    ]


def _row(
    opportunity: Opportunity,
    contacts_by_opportunity: dict[tuple[str, str], list[RankedContact]] | None = None,
) -> list[str | int | float]:
    roles = opportunity.decision_maker_role + ["", ""]
    row: list[str | int | float] = [
        datetime.now(timezone.utc).date().isoformat(),
        opportunity.priority,
        opportunity.score,
        opportunity.company_name,
        opportunity.molecule_name,
        "; ".join(opportunity.likely_need_type),
        opportunity.rationale,
        roles[0],
        roles[1],
        len(opportunity.signal_fingerprints),
        opportunity.last_signal_at.isoformat() if opportunity.last_signal_at else "",
    ]
    contacts = (contacts_by_opportunity or {}).get((opportunity.company_name, opportunity.molecule_name), [])
    for index in range(3):
        row.extend(_contact_values(contacts[index] if index < len(contacts) else None))
    return row


def export_csv(
    opportunities: list[Opportunity],
    path: str | Path,
    contacts_by_opportunity: dict[tuple[str, str], list[RankedContact]] | None = None,
) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(_HEADERS)
        for opportunity in opportunities:
            writer.writerow(_row(opportunity, contacts_by_opportunity))
    return destination


def export_xlsx(
    opportunities: list[Opportunity],
    path: str | Path,
    contacts_by_opportunity: dict[tuple[str, str], list[RankedContact]] | None = None,
) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = "Opportunities"
    worksheet.append(_HEADERS)
    for cell in worksheet[1]:
        cell.font = Font(bold=True)
    worksheet.freeze_panes = "A2"
    for opportunity in opportunities:
        worksheet.append(_row(opportunity, contacts_by_opportunity))
    workbook.save(destination)
    return destination
