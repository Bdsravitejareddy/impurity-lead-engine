from impurity_leads.contacts.models import ContactCandidate
from impurity_leads.contacts.normalize import title_family
from impurity_leads.models import Opportunity


def _target_families(opportunity: Opportunity) -> set[str]:
    context = " ".join(opportunity.likely_need_type).casefold()
    targets: set[str] = set()
    if any(token in context for token in ("nitrosamine", "ndsri", "genotoxic")):
        targets.update({"analytical", "cmc", "quality", "regulatory", "toxicology"})
    if any(token in context for token in ("degradation", "process impurity", "impurity synthesis", "impurity")):
        targets.update({"analytical", "api_process", "cmc", "quality"})
    if any(token in context for token in ("stability", "forced degradation")):
        targets.update({"analytical", "stability", "quality", "cmc"})
    if any(token in context for token in ("regulatory", "anda", "nda", "cmc")):
        targets.update({"cmc", "analytical", "regulatory", "api_process"})
    if any(token in context for token in ("rfq", "tender", "sourcing", "procurement")):
        targets.update({"procurement", "analytical", "cmc"})
    if any(token in context for token in ("phase ii", "phase iii", "late-stage", "late stage")):
        targets.update({"cmc", "analytical", "api_process"})
    return targets or {"analytical", "cmc", "api_process", "quality", "procurement"}


def _seniority_score(title: str) -> int:
    value = title.casefold()
    if any(token in value for token in ("svp", "senior vice president", "vice president", "vp", "head of", "head,")):
        return 20
    if "executive director" in value:
        return 20
    if "associate director" in value:
        return 12
    if "director" in value:
        return 15
    if any(token in value for token in ("senior manager", "group leader")):
        return 10
    if any(token in value for token in ("manager", "principal scientist")):
        return 8
    if any(token in value for token in ("senior scientist", "scientist")):
        return 4
    return 0


def score_role_fit(
    opportunity: Opportunity,
    contact: ContactCandidate,
    source_type: str | None = None,
) -> tuple[int, str]:
    title = contact.title or ""
    family = contact.department or title_family(title)
    targets = _target_families(opportunity)
    score = 0
    reasons: list[str] = []

    if family in targets:
        score += 35
        reasons.append(f"target function: {family}")

    title_lower = title.casefold()
    functional_keywords = {
        "analytical": ("analytical", "bioanalytical"),
        "cmc": ("cmc", "chemistry manufacturing", "technical operations"),
        "api_process": ("api", "process development", "process chemistry"),
        "quality": ("quality", "quality control", "compliance"),
        "regulatory": ("regulatory",),
        "procurement": ("procurement", "sourcing", "purchasing", "buyer"),
        "stability": ("stability",),
        "toxicology": ("toxicology", "toxicologist"),
    }
    if family and any(token in title_lower for token in functional_keywords.get(family, ())):
        score += 25
        reasons.append("explicit function keyword")

    seniority = _seniority_score(title)
    score += seniority
    if seniority:
        reasons.append("relevant seniority")

    if source_type == "company_site":
        score += 10
        reasons.append("company-controlled source")

    context = " ".join(opportunity.likely_need_type).casefold()
    if family == "procurement" and any(token in context for token in ("rfq", "tender")):
        score += 25
        reasons.append("procurement owner for direct RFQ/tender")

    if family == "executive":
        score -= 30
        reasons.append("generic executive penalty")

    if any(token in title_lower for token in ("principal investigator", "study investigator", "site investigator")):
        score -= 25
        reasons.append("clinical investigator penalty")

    score = max(0, min(100, score))
    return score, "; ".join(reasons) if reasons else "limited functional evidence"
