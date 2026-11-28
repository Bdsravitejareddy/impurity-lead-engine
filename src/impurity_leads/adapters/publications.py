"""Company-authored impurity papers from Europe PMC as a lead source.

When a company's own scientists publish on the impurities, degradation
products or nitrosamines of a drug, that is direct, dated evidence the company
is doing impurity work on that molecule. New papers appear every week, so
this keeps the lead list moving.

Only papers with an author whose own affiliation is a company count; papers
written entirely at universities or hospitals are skipped. The molecule comes
from the paper's indexed chemical list (specific compounds, not classes such
as "Nitrosamines"), else from a drug-like name in the title.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

from impurity_leads.adapters.base import SourceAdapter
from impurity_leads.models import SourceRecord

_COMPANY = re.compile(
    r"\b(ltd|limited|pvt|inc|llc|gmbh|ag|s\.?a\.?|s\.?p\.?a\.?|corp|corporation|co\.|laborator(?:y|ies)|labs|"
    r"pharmaceuticals?|pharma|biotech|biosciences|therapeutics|lifesciences|life sciences|healthcare)\b",
    re.I,
)
_ACADEMIC = re.compile(
    r"universit|college|school|institut|hospital|klinik|klinikum|academy|faculty|centre for|center for|council|ministry|"
    r"national|deemed|polytechnic|clinic\b|research center|research centre|key laboratory|state key",
    re.I,
)
_SUFFIX_ONLY = re.compile(r"^(ltd|limited|pvt\.? ltd|inc|llc|gmbh|ag|s\.?a|corp|co)\.?$", re.I)
# Units inside an organisation, not its name.
_DEPARTMENT = re.compile(r"\b(department|division|r&d|research and development|analytical|quality|process|"
                         r"development|technologies|unit|group|centre|center|site|plant)\b", re.I)
# Chemical-list entries that name a class or a reagent, not the drug studied.
_GENERIC_CHEMICALS = {
    "water", "solvents", "pharmaceutical preparations", "drug contamination", "acetonitriles", "methanol",
    "nitrosamines", "mutagens", "carcinogens", "nitrites", "impurities", "reference standards",
}
_DRUG_SUFFIX = re.compile(
    r"^[a-z]{3,}(?:mab|nib|tinib|ciclib|pril|sartan|olol|statin|azole|prazole|cillin|mycin|floxacin|tidine|"
    r"gliptin|gliflozin|parin|vir|dipine|oxetine|triptan|semide|thiazide|caine|lukast|setron|afil|asone|olone|"
    r"zepam|azepam|barbital|profen|fenac|coxib|lamide|tadine|platin|rubicin|taxel|lukast|gatran|xaban|"
    r"terol|fylline|conazole|navir|buvir|previr|asvir|mod|imod|zomib|lisib|parib|degib|rafenib|cycline|"
    r"amivir|amide|osin|azosin|dronate|tropin)$",
    re.I,
)
_TITLE_WORD = re.compile(r"[A-Za-z][A-Za-z-]{4,}")
# RxNorm lists these, but a paper on them is not a drug-impurity lead.
_NOT_A_LEAD_MOLECULE = {"zinc", "diatomaceous earth", "methamphetamine", "ethanol", "glucose", "sodium chloride",
                        "caffeine", "nicotine", "cocaine", "heroin", "fentanyl", "cannabidiol",
                        # Excipients and biomaterials: their papers are about formulation, not an API.
                        "cellulose", "microcrystalline cellulose", "lactose", "magnesium stearate", "povidone",
                        "crospovidone", "starch", "talc", "titanium dioxide", "mannitol", "sucrose", "gelatin",
                        "hyaluronic acid", "chitosan", "polyethylene glycols", "polysorbate 80"}
_NOT_A_LEAD_PREFIX = ("collagen", "phosph", "silic")
# Firms that sell impurity standards or testing: competitors and labs, not buyers.
_VENDOR_OR_LAB = re.compile(
    r"sigma|merck kgaa|millipore|lgc|toronto research|clearsynth|pharmaffiliates|simson|daicel|synzeal|"
    r"veeprho|axios research|cerilliant|usp\b|pharmacopeia|testing|analytical services|eurofins|sgs\b|"
    r"intertek|charles river|labcorp|waters corp|agilent|thermo fisher|shimadzu|sciex",
    re.I,
)


def company_from_affiliation(affiliation: str) -> str | None:
    """'Analytical R&D, Dr. Reddy's Laboratories Ltd., Hyderabad' -> "Dr. Reddy's Laboratories Ltd"."""
    if not affiliation or _ACADEMIC.search(affiliation):
        return None
    segments = [segment.strip(" .") for segment in affiliation.split(",")]
    for index, segment in enumerate(segments):
        if not segment or "@" in segment:
            continue
        if _SUFFIX_ONLY.match(segment) and index > 0:
            # 'Amgen, Inc.' -> 'Amgen Inc'
            return f"{segments[index - 1]} {segment}".strip()
        if _COMPANY.search(segment) and not (_DEPARTMENT.search(segment) and not _COMPANY.search(segment.split()[-1])):
            return segment
    return None


def _affiliations(item: dict) -> list[str]:
    output = []
    for author in (item.get("authorList") or {}).get("author", []) or []:
        rows = (author.get("authorAffiliationDetailsList") or {}).get("authorAffiliation") or []
        output.extend(str(row.get("affiliation")) for row in rows if isinstance(row, dict) and row.get("affiliation"))
        if author.get("affiliation"):
            output.append(str(author["affiliation"]))
    if item.get("affiliation"):
        output.append(str(item["affiliation"]))
    return output


def molecule_from_paper(item: dict) -> str | None:
    for chemical in (item.get("chemicalList") or {}).get("chemical", []) or []:
        name = str(chemical.get("name") or "").strip()
        lowered = name.lower()
        if not name or lowered in _GENERIC_CHEMICALS or "," in name or lowered.endswith("s"):
            continue
        return name
    for word in _TITLE_WORD.findall(str(item.get("title") or "")):
        if _DRUG_SUFFIX.match(word):
            return word
    return None


def _date(value: str | None) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value)[:10]).replace(tzinfo=timezone.utc) if value else None
    except ValueError:
        return None


class PublicationAdapter(SourceAdapter):
    name = "europe_pmc"

    def __init__(self, is_drug=None):
        # is_drug(name) -> bool confirms the molecule is a real drug (RxNorm in
        # the crawl); without it every named molecule is accepted.
        self.is_drug = is_drug

    def parse(self, item: dict) -> list[SourceRecord]:
        companies = list(dict.fromkeys(
            company for company in (company_from_affiliation(a) for a in _affiliations(item))
            if company and not _VENDOR_OR_LAB.search(company)
        ))
        molecule = molecule_from_paper(item)
        if molecule and (molecule.lower() in _NOT_A_LEAD_MOLECULE or molecule.lower().startswith(_NOT_A_LEAD_PREFIX) or (self.is_drug and not self.is_drug(molecule))):
            return []
        identifier = item.get("pmid") or item.get("id")
        if not companies or not molecule or not identifier:
            return []
        source = "MED" if item.get("pmid") else str(item.get("source") or "MED")
        title = str(item.get("title") or "").strip()
        abstract = re.sub(r"<[^>]+>", " ", str(item.get("abstractText") or ""))
        text = re.sub(r"\s+", " ", f"{title} {abstract}").strip()[:1500]
        published = _date(item.get("firstPublicationDate"))
        # One record per company named; a paper by two companies supports both.
        return [SourceRecord(
            source_name=self.name,
            source_type="publication",
            source_record_id=str(identifier),
            source_url=f"https://europepmc.org/article/{source}/{identifier}",
            published_at=published,
            fetched_at=datetime.now(timezone.utc),
            company_name_raw=company,
            molecule_name_raw=molecule,
            active_ingredient_raw=molecule,
            signal_text=text,
            metadata_json={"pmid": item.get("pmid"), "doi": item.get("doi"), "journal": item.get("journalTitle"),
                           "publication_title": title[:300]},
        ) for company in companies[:3]]
