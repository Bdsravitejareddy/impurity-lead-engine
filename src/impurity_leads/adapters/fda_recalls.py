"""FDA enforcement reports for drug recalls caused by impurities.

A recall for failed impurity or degradation specifications, or for nitrosamines
above the FDA limit, means the firm must investigate, identify and control that
impurity. That is direct, dated demand for impurity standards and analytical
work, so each recall becomes an ``impurity_recall`` signal.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

from impurity_leads.adapters.base import SourceAdapter
from impurity_leads.models import SourceRecord

# Words that describe the product form, not the molecule.
_FORM_WORDS = re.compile(
    r"\b(tablets?|capsules?|injection|injectable|solution|suspension|oral|ophthalmic|topical|cream|ointment|gel|"
    r"extended[- ]release|delayed[- ]release|orally disintegrating|chewable|film[- ]coated|for|usp|nf|rx only|"
    r"inhalation|nasal|spray|powder|syrup|elixir|drops|lotion|patch|vial|kit|sterile)\b.*",
    re.I,
)
IMPURITY_REASON = re.compile(r"impurit|nitros|n-nitroso|ndsri|degradat", re.I)
# Repackagers and distributors relabel another firm's product. The manufacturer
# owns the impurity work, so their recalls are not leads.
REPACKAGER = re.compile(
    r"repack|packag|\brx\b|pd-rx|direct rx|avkare|amerisource|cardinal health|mckesson|harvard drug|"
    r"major pharmaceuticals|rugby|preferred pharmaceuticals|asclemed|golden state medical|precision dose|"
    r"quality care|bryant ranch|proficient rx|nucare|a-s medication|aphena|northwind|henry schein|medsource|"
    r"unit dose|lake erie medical",
    re.I,
)


def molecule_from_description(description: str) -> str | None:
    """'Ciprofloxacin Tablets, USP, 750 mg' -> 'Ciprofloxacin'."""
    head = re.split(r"[,;(]|\d", description or "", maxsplit=1)[0]
    head = _FORM_WORDS.sub("", head).strip(" -/")
    return head or None


def _date(value: str | None) -> datetime | None:
    if value and len(value) == 8 and value.isdigit():
        return datetime.strptime(value, "%Y%m%d").replace(tzinfo=timezone.utc)
    return None


class FDARecallAdapter(SourceAdapter):
    name = "openfda_recall"

    def parse(self, payload: dict) -> list[SourceRecord]:
        reason = str(payload.get("reason_for_recall") or "").strip()
        firm = str(payload.get("recalling_firm") or "").strip()
        if not firm or not IMPURITY_REASON.search(reason) or REPACKAGER.search(firm):
            return []
        openfda = payload.get("openfda") or {}
        names = openfda.get("substance_name") or openfda.get("generic_name") or []
        molecule = names[0] if names else molecule_from_description(payload.get("product_description") or "")
        if not molecule:
            return []
        recall_number = payload.get("recall_number")
        initiated = _date(payload.get("recall_initiation_date"))
        product = str(payload.get("product_description") or "")[:200]
        return [SourceRecord(
            source_name=self.name,
            source_type="recall",
            source_record_id=recall_number,
            source_url=f"https://api.fda.gov/drug/enforcement.json?search=recall_number:%22{recall_number}%22",
            published_at=initiated,
            fetched_at=datetime.now(timezone.utc),
            company_name_raw=firm,
            molecule_name_raw=molecule,
            active_ingredient_raw=molecule,
            country=payload.get("country"),
            signal_text=f"FDA recall {recall_number}: {product}. Reason: {reason}",
            metadata_json={
                "recall_number": recall_number,
                "recall_reason": reason[:300],
                "recall_class": payload.get("classification"),
                "recall_status": payload.get("status"),
                "report_date": payload.get("report_date"),
                "application_numbers": openfda.get("application_number") or [],
            },
        )]
