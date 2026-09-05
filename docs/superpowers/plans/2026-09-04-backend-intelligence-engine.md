# Backend Intelligence Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a zero-cost, testable Python backend that discovers molecule-level impurity-synthesis demand signals, normalizes them, scores opportunities, stores them in Supabase, and exports qualified leads.

**Architecture:** A small Python package exposes deterministic source adapters, entity normalization, extraction, scoring, deduplication, persistence, and export as isolated modules. All source adapters emit the same `SourceRecord` contract; the pipeline converts records into structured `Signal` objects and aggregates `(company, molecule)` opportunities before writing to Supabase. Network-heavy crawling is incremental and budgeted, while tests use local fixtures only.

**Tech Stack:** Python 3.12, `httpx`, `beautifulsoup4`, `lxml`, `python-dateutil`, `pydantic>=2`, `supabase` Python client, `openpyxl`, `pytest`, GitHub Actions, Supabase PostgreSQL.

**Spec:** `docs/superpowers/specs/2026-09-04-impurity-lead-engine-design.md`

## Global Constraints

- Operating cost must remain ₹0/month.
- No paid search APIs, enrichment APIs, or LLM calls.
- No CAPTCHA bypass, authenticated-site scraping, LinkedIn automation, or raw-page storage.
- Direct website crawling must obey robots.txt, domain rate limits, and Retry-After.
- Persist only structured entities, signals, evidence snippets, run metadata, and qualified opportunities.
- Default qualification requires a resolvable company, a resolvable molecule/API, at least one non-generic signal, and no competitor exclusion.
- `HOT`: score >= 80 or direct RFQ; `HIGH`: 65–79; `REVIEW`: 50–64; below 50 is not in the default queue.
- GitHub Actions production crawl target: average under 45 minutes/day and under 1,350 private-runner minutes/month.
- Supabase database safety target: below 350 MB.
- Use current Supabase publishable/secret keys; never ship a secret key to browser code.
- RLS must be enabled on every exposed Supabase table, with explicit grants.

---

## File Structure

```text
pyproject.toml
README.md
.env.example
src/impurity_leads/
  __init__.py
  config.py
  models.py
  normalize.py
  extract.py
  classify.py
  score.py
  dedupe.py
  aggregate.py
  pipeline.py
  export.py
  storage/
    __init__.py
    base.py
    memory.py
    supabase_store.py
  adapters/
    __init__.py
    base.py
    clinical_trials.py
    fda.py
    company_site.py
    common_crawl.py
  crawling/
    __init__.py
    robots.py
    fetch.py
    sitemap.py
  cli.py
scripts/
  run_daily.py
supabase/
  schema.sql
tests/
  fixtures/
    clinical_trials_study.json
    fda_record.json
    company_job.html
    company_pipeline.html
    impurity_vendor.html
    tender_rfq.html
  test_models.py
  test_normalize.py
  test_extract.py
  test_classify.py
  test_score.py
  test_dedupe.py
  test_aggregate.py
  test_export.py
  test_pipeline.py
  adapters/
    test_clinical_trials.py
    test_fda.py
    test_company_site.py
    test_common_crawl.py
  crawling/
    test_robots.py
    test_sitemap.py
.github/workflows/
  test.yml
  daily-crawl.yml
```

---

### Task 1: Python package foundation and contracts

**Files:**
- Create: `pyproject.toml`
- Create: `src/impurity_leads/__init__.py`
- Create: `src/impurity_leads/config.py`
- Create: `src/impurity_leads/models.py`
- Create: `tests/test_models.py`
- Create: `.env.example`

**Interfaces:**
- Produces: `SourceRecord`, `CompanyRef`, `MoleculeRef`, `Signal`, `Opportunity`, `CrawlRunStats`, `Settings`.
- Later tasks import these exact model names from `impurity_leads.models`.

- [ ] **Step 1: Write failing model validation tests**

```python
# tests/test_models.py
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
```

- [ ] **Step 2: Run tests and verify they fail because the package does not exist**

Run: `python -m pytest tests/test_models.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'impurity_leads'`.

- [ ] **Step 3: Create package metadata and model contracts**

```toml
# pyproject.toml
[build-system]
requires = ["setuptools>=75", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "impurity-lead-engine"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
  "beautifulsoup4>=4.12,<5",
  "httpx>=0.28,<1",
  "lxml>=5,<6",
  "openpyxl>=3.1,<4",
  "pydantic>=2.9,<3",
  "python-dateutil>=2.9,<3",
  "supabase>=2.18,<3",
]

[project.optional-dependencies]
dev = ["pytest>=8.3,<9"]

[project.scripts]
impurity-leads = "impurity_leads.cli:main"

[tool.pytest.ini_options]
pythonpath = ["src"]
testpaths = ["tests"]
```

```python
# src/impurity_leads/models.py
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
```

```python
# src/impurity_leads/config.py
import os
from pydantic import BaseModel


class Settings(BaseModel):
    user_agent: str = "SVAK-Impurity-Lead-Research/0.1"
    request_timeout_seconds: float = 20.0
    per_domain_delay_seconds: float = 1.0
    max_retries: int = 2
    run_deadline_minutes: int = 42
    supabase_url: str | None = None
    supabase_secret_key: str | None = None


def load_settings() -> Settings:
    return Settings(
        user_agent=os.getenv("CRAWLER_USER_AGENT", "SVAK-Impurity-Lead-Research/0.1"),
        supabase_url=os.getenv("SUPABASE_URL"),
        supabase_secret_key=os.getenv("SUPABASE_SECRET_KEY"),
    )
```

```text
# .env.example
CRAWLER_USER_AGENT=SVAK-Impurity-Lead-Research/0.1 (+contact@example.com)
SUPABASE_URL=
SUPABASE_SECRET_KEY=
```

- [ ] **Step 4: Run model tests**

Run: `python -m pytest tests/test_models.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml .env.example src/impurity_leads tests/test_models.py
git commit -m "feat: add core data contracts"
```

---

### Task 2: Entity normalization and deterministic extraction

**Files:**
- Create: `src/impurity_leads/normalize.py`
- Create: `src/impurity_leads/extract.py`
- Create: `tests/test_normalize.py`
- Create: `tests/test_extract.py`

**Interfaces:**
- Produces: `normalize_company_name(name: str) -> str`, `normalize_molecule_name(name: str) -> str`, `extract_cas_numbers(text: str) -> list[str]`, `extract_quantities(text: str) -> list[str]`, `extract_evidence_windows(text: str, phrases: list[str], window: int = 180) -> list[str]`.

- [ ] **Step 1: Write failing normalization and extraction tests**

```python
# tests/test_normalize.py
from impurity_leads.normalize import normalize_company_name, normalize_molecule_name


def test_company_normalization_removes_common_legal_suffixes():
    assert normalize_company_name("Example Pharma, Inc.") == "example pharma"


def test_molecule_normalization_preserves_development_code():
    assert normalize_molecule_name("  ABC-123 ") == "abc-123"
```

```python
# tests/test_extract.py
from impurity_leads.extract import extract_cas_numbers, extract_quantities, extract_evidence_windows


def test_extracts_valid_cas_number_and_quantity():
    text = "Required impurity CAS 12345-67-8, quantity 50 mg with NMR."
    assert extract_cas_numbers(text) == ["12345-67-8"]
    assert extract_quantities(text) == ["50 mg"]


def test_evidence_window_contains_keyword():
    text = "A" * 250 + " degradation impurity characterization for Drug X " + "B" * 250
    windows = extract_evidence_windows(text, ["degradation impurity"], window=60)
    assert len(windows) == 1
    assert "degradation impurity" in windows[0].lower()
```

- [ ] **Step 2: Run tests and verify import failures**

Run: `python -m pytest tests/test_normalize.py tests/test_extract.py -v`
Expected: FAIL because modules do not exist.

- [ ] **Step 3: Implement minimal deterministic normalizers and extractors**

```python
# src/impurity_leads/normalize.py
import re

_COMPANY_SUFFIX = re.compile(r"\b(incorporated|inc|limited|ltd|llc|plc|corp|corporation|co)\.?$", re.I)


def _clean(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().lower())


def normalize_company_name(name: str) -> str:
    value = re.sub(r"[,]+", "", _clean(name))
    value = _COMPANY_SUFFIX.sub("", value).strip(" .")
    return re.sub(r"\s+", " ", value)


def normalize_molecule_name(name: str) -> str:
    return _clean(name).strip(" ,.;:")
```

```python
# src/impurity_leads/extract.py
import re

_CAS_RE = re.compile(r"\b\d{2,7}-\d{2}-\d\b")
_QTY_RE = re.compile(r"\b\d+(?:\.\d+)?\s?(?:mg|g|kg)\b", re.I)


def extract_cas_numbers(text: str) -> list[str]:
    return list(dict.fromkeys(_CAS_RE.findall(text)))


def extract_quantities(text: str) -> list[str]:
    return list(dict.fromkeys(m.group(0).replace("  ", " ") for m in _QTY_RE.finditer(text)))


def extract_evidence_windows(text: str, phrases: list[str], window: int = 180) -> list[str]:
    lowered = text.lower()
    output: list[str] = []
    for phrase in phrases:
        start = 0
        needle = phrase.lower()
        while True:
            index = lowered.find(needle, start)
            if index < 0:
                break
            left = max(0, index - window)
            right = min(len(text), index + len(needle) + window)
            snippet = re.sub(r"\s+", " ", text[left:right]).strip()
            if snippet not in output:
                output.append(snippet)
            start = index + len(needle)
    return output
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_normalize.py tests/test_extract.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/impurity_leads/normalize.py src/impurity_leads/extract.py tests/test_normalize.py tests/test_extract.py
git commit -m "feat: add deterministic extraction"
```

---

### Task 3: Signal classification, vendor exclusion, and fingerprinting

**Files:**
- Create: `src/impurity_leads/classify.py`
- Create: `src/impurity_leads/dedupe.py`
- Create: `tests/test_classify.py`
- Create: `tests/test_dedupe.py`

**Interfaces:**
- Produces: `classify_signal(text: str, has_molecule: bool) -> list[tuple[str, int, str]]`, `looks_like_impurity_vendor(text: str) -> bool`, `signal_fingerprint(...) -> str`.

- [ ] **Step 1: Write failing classifier tests**

```python
# tests/test_classify.py
from impurity_leads.classify import classify_signal, looks_like_impurity_vendor


def test_named_molecule_nitrosamine_is_high_intent():
    matches = classify_signal("NDSRI nitrosamine assessment for Drug X", has_molecule=True)
    assert ("nitrosamine_ndsri", 45, "nitrosamine/NDSRI") in matches


def test_vendor_language_is_excluded():
    text = "We manufacture and supply custom impurity reference standards worldwide."
    assert looks_like_impurity_vendor(text) is True
```

```python
# tests/test_dedupe.py
from impurity_leads.dedupe import signal_fingerprint


def test_fingerprint_is_stable_for_whitespace_changes():
    first = signal_fingerprint("example pharma", "drug x", "nitrosamine_ndsri", "https://a.com/x", "NDSRI  work")
    second = signal_fingerprint("example pharma", "drug x", "nitrosamine_ndsri", "https://a.com/x", "NDSRI work")
    assert first == second
```

- [ ] **Step 2: Run tests and verify failures**

Run: `python -m pytest tests/test_classify.py tests/test_dedupe.py -v`
Expected: FAIL because modules do not exist.

- [ ] **Step 3: Implement deterministic rules**

```python
# src/impurity_leads/classify.py
from dataclasses import dataclass


@dataclass(frozen=True)
class Rule:
    signal_type: str
    phrases: tuple[str, ...]
    weight_with_molecule: int
    weight_without_molecule: int
    need_type: str


RULES = (
    Rule("direct_impurity_rfq", ("request for quotation", "rfq", "required impurity"), 70, 45, "custom impurity synthesis"),
    Rule("reference_standard", ("reference standard", "working standard"), 60, 25, "reference standard"),
    Rule("nitrosamine_ndsri", ("ndsri", "nitrosamine", "n-nitroso"), 45, 20, "nitrosamine/NDSRI"),
    Rule("genotoxic_impurity", ("genotoxic impurity", "ich m7"), 40, 18, "genotoxic impurity"),
    Rule("impurity_characterization", ("impurity characterization", "impurity isolation", "structure elucidation"), 38, 15, "impurity characterization"),
    Rule("degradation_product", ("degradation product", "degradation impurity"), 35, 15, "degradation impurity"),
    Rule("stability", ("forced degradation", "stability-indicating", "stability study"), 18, 8, "stability/degradation"),
    Rule("method_validation", ("method validation", "analytical method development"), 12, 5, "analytical development"),
)

_VENDOR_PHRASES = (
    "we manufacture impurity",
    "we manufacture and supply",
    "impurity standards supplier",
    "reference standards supplier",
    "custom impurity synthesis services",
    "catalogue of impurities",
)


def classify_signal(text: str, has_molecule: bool) -> list[tuple[str, int, str]]:
    lowered = text.lower()
    matches: list[tuple[str, int, str]] = []
    for rule in RULES:
        if any(phrase in lowered for phrase in rule.phrases):
            matches.append((rule.signal_type, rule.weight_with_molecule if has_molecule else rule.weight_without_molecule, rule.need_type))
    return matches


def looks_like_impurity_vendor(text: str) -> bool:
    lowered = text.lower()
    return any(phrase in lowered for phrase in _VENDOR_PHRASES)
```

```python
# src/impurity_leads/dedupe.py
import hashlib
import re
from urllib.parse import urlsplit, urlunsplit


def canonical_url(url: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/"), "", ""))


def _norm(text: str | None) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def signal_fingerprint(company: str, molecule: str | None, signal_type: str, source_url: str, evidence_text: str) -> str:
    payload = "|".join((_norm(company), _norm(molecule), signal_type, canonical_url(source_url), _norm(evidence_text)))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
```

- [ ] **Step 4: Run classifier tests**

Run: `python -m pytest tests/test_classify.py tests/test_dedupe.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/impurity_leads/classify.py src/impurity_leads/dedupe.py tests/test_classify.py tests/test_dedupe.py
git commit -m "feat: classify and deduplicate signals"
```

---

### Task 4: Opportunity scoring and aggregation

**Files:**
- Create: `src/impurity_leads/score.py`
- Create: `src/impurity_leads/aggregate.py`
- Create: `tests/test_score.py`
- Create: `tests/test_aggregate.py`

**Interfaces:**
- Produces: `freshness_penalty(event_date, now) -> int`, `score_signals(signals, is_vendor=False) -> int`, `aggregate_opportunities(signals) -> list[Opportunity]`.

- [ ] **Step 1: Write failing scoring tests**

```python
# tests/test_score.py
from datetime import datetime, timedelta, timezone
from impurity_leads.models import Signal
from impurity_leads.score import score_signals


def make_signal(weight: int, days_old: int = 0) -> Signal:
    now = datetime.now(timezone.utc)
    return Signal(
        company_name="Example Pharma",
        molecule_name="Drug X",
        source_type="job",
        signal_type="impurity_characterization",
        source_url=f"https://example.com/{weight}/{days_old}",
        evidence_text="impurity characterization",
        event_date=now - timedelta(days=days_old),
        discovered_at=now,
        base_weight=weight,
        confidence=1.0,
        fingerprint=f"{weight}-{days_old}",
    )


def test_scoring_applies_freshness_penalty():
    assert score_signals([make_signal(70, 400)]) == 40


def test_vendor_exclusion_zeroes_score():
    assert score_signals([make_signal(70)], is_vendor=True) == 0
```

```python
# tests/test_aggregate.py
from datetime import datetime, timezone
from impurity_leads.aggregate import aggregate_opportunities
from impurity_leads.models import Signal


def test_aggregate_requires_company_and_molecule_and_surfaces_high():
    now = datetime.now(timezone.utc)
    signals = [
        Signal(company_name="Example Pharma", molecule_name="Drug X", source_type="trial", signal_type="phase_iii", source_url="https://a", evidence_text="Phase III", discovered_at=now, base_weight=18, confidence=1.0, fingerprint="a"),
        Signal(company_name="Example Pharma", molecule_name="Drug X", source_type="job", signal_type="impurity_characterization", source_url="https://b", evidence_text="impurity characterization", discovered_at=now, base_weight=38, confidence=1.0, fingerprint="b"),
        Signal(company_name="Example Pharma", molecule_name="Drug X", source_type="site", signal_type="stability", source_url="https://c", evidence_text="forced degradation", discovered_at=now, base_weight=18, confidence=1.0, fingerprint="c"),
    ]
    opportunities = aggregate_opportunities(signals)
    assert len(opportunities) == 1
    assert opportunities[0].priority in {"HIGH", "HOT"}
```

- [ ] **Step 2: Run tests and verify failures**

Run: `python -m pytest tests/test_score.py tests/test_aggregate.py -v`
Expected: FAIL because scoring modules do not exist.

- [ ] **Step 3: Implement freshness, source bonus, score caps, and role inference**

```python
# src/impurity_leads/score.py
from datetime import datetime, timezone
from impurity_leads.models import Signal


def freshness_penalty(event_date: datetime | None, now: datetime | None = None) -> int:
    if event_date is None:
        return 0
    now = now or datetime.now(timezone.utc)
    days = max(0, (now - event_date).days)
    if days > 365:
        return -30
    if days >= 180:
        return -15
    return 0


def score_signals(signals: list[Signal], is_vendor: bool = False) -> int:
    if is_vendor or not signals:
        return 0
    raw = sum(s.base_weight + freshness_penalty(s.event_date) for s in signals)
    independent_sources = len({s.source_type for s in signals})
    if independent_sources >= 3:
        raw += 8
    elif independent_sources == 2:
        raw += 4
    return max(0, min(100, raw))
```

```python
# src/impurity_leads/aggregate.py
from collections import defaultdict
from impurity_leads.models import Opportunity, Signal
from impurity_leads.score import score_signals

_ROLE_MAP = {
    "impurity_characterization": ["Head/Director Analytical R&D"],
    "degradation_product": ["Head/Director Analytical R&D"],
    "nitrosamine_ndsri": ["Analytical Development", "Quality", "Regulatory CMC"],
    "genotoxic_impurity": ["Analytical Development", "Regulatory CMC"],
    "reference_standard": ["Analytical R&D", "Strategic Sourcing/Procurement"],
    "direct_impurity_rfq": ["Analytical R&D", "Strategic Sourcing/Procurement"],
}


def _priority(score: int, signal_types: set[str]) -> str | None:
    if score >= 80 or "direct_impurity_rfq" in signal_types:
        return "HOT"
    if score >= 65:
        return "HIGH"
    if score >= 50:
        return "REVIEW"
    return None


def aggregate_opportunities(signals: list[Signal]) -> list[Opportunity]:
    grouped: dict[tuple[str, str], list[Signal]] = defaultdict(list)
    for signal in signals:
        if signal.company_name and signal.molecule_name:
            grouped[(signal.company_name, signal.molecule_name)].append(signal)

    output: list[Opportunity] = []
    for (company, molecule), group in grouped.items():
        unique = list({s.fingerprint: s for s in group}.values())
        score = score_signals(unique)
        types = {s.signal_type for s in unique}
        priority = _priority(score, types)
        if priority is None:
            continue
        needs = sorted({s.metadata_json.get("need_type", s.signal_type) for s in unique})
        roles: list[str] = []
        for signal_type in types:
            for role in _ROLE_MAP.get(signal_type, []):
                if role not in roles:
                    roles.append(role)
        latest = max((s.event_date or s.discovered_at for s in unique), default=None)
        rationale = "; ".join(sorted({s.signal_type.replace("_", " ") for s in unique}))
        output.append(Opportunity(
            company_name=company,
            molecule_name=molecule,
            score=score,
            priority=priority,
            likely_need_type=needs,
            rationale=rationale,
            decision_maker_role=roles[:3],
            signal_fingerprints=[s.fingerprint for s in unique],
            last_signal_at=latest,
        ))
    return sorted(output, key=lambda item: item.score, reverse=True)
```

- [ ] **Step 4: Run scoring tests**

Run: `python -m pytest tests/test_score.py tests/test_aggregate.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/impurity_leads/score.py src/impurity_leads/aggregate.py tests/test_score.py tests/test_aggregate.py
git commit -m "feat: score molecule opportunities"
```

---

### Task 5: ClinicalTrials.gov and FDA source adapters

**Files:**
- Create: `src/impurity_leads/adapters/__init__.py`
- Create: `src/impurity_leads/adapters/base.py`
- Create: `src/impurity_leads/adapters/clinical_trials.py`
- Create: `src/impurity_leads/adapters/fda.py`
- Create: `tests/fixtures/clinical_trials_study.json`
- Create: `tests/fixtures/fda_record.json`
- Create: `tests/adapters/test_clinical_trials.py`
- Create: `tests/adapters/test_fda.py`

**Interfaces:**
- Produces: `SourceAdapter.parse(payload) -> list[SourceRecord]`, `ClinicalTrialsAdapter`, `FDAAdapter`.
- The network fetch methods use official public APIs; parser tests use fixtures only.

- [ ] **Step 1: Add representative fixtures and failing parser tests**

```python
# tests/adapters/test_clinical_trials.py
import json
from pathlib import Path
from impurity_leads.adapters.clinical_trials import ClinicalTrialsAdapter


def test_trial_parser_emits_company_and_molecule():
    payload = json.loads(Path("tests/fixtures/clinical_trials_study.json").read_text())
    records = ClinicalTrialsAdapter().parse(payload)
    assert records[0].company_name_raw == "Example Pharma"
    assert records[0].molecule_name_raw == "EX-101"
    assert records[0].metadata_json["phase"] == "PHASE3"
```

```python
# tests/adapters/test_fda.py
import json
from pathlib import Path
from impurity_leads.adapters.fda import FDAAdapter


def test_fda_parser_emits_applicant_and_active_ingredient():
    payload = json.loads(Path("tests/fixtures/fda_record.json").read_text())
    records = FDAAdapter().parse(payload)
    assert records[0].company_name_raw == "Example Pharma"
    assert records[0].active_ingredient_raw == "Drug X"
```

- [ ] **Step 2: Run adapter tests and verify failures**

Run: `python -m pytest tests/adapters/test_clinical_trials.py tests/adapters/test_fda.py -v`
Expected: FAIL because adapters do not exist.

- [ ] **Step 3: Implement adapter contract and parsers**

```python
# src/impurity_leads/adapters/base.py
from abc import ABC, abstractmethod
from impurity_leads.models import SourceRecord


class SourceAdapter(ABC):
    name: str

    @abstractmethod
    def parse(self, payload: dict) -> list[SourceRecord]:
        raise NotImplementedError
```

ClinicalTrials parsing must read `protocolSection.identificationModule`, `sponsorCollaboratorsModule`, `armsInterventionsModule`, `designModule`, and status dates; it emits one record per drug intervention with the lead sponsor as company and phase in metadata.

FDA parsing must read one result at a time and map applicant/manufacturer and active ingredient/product fields into `SourceRecord`, storing NDA/ANDA/application identifiers in metadata.

- [ ] **Step 4: Run parser tests**

Run: `python -m pytest tests/adapters/test_clinical_trials.py tests/adapters/test_fda.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/impurity_leads/adapters tests/fixtures/clinical_trials_study.json tests/fixtures/fda_record.json tests/adapters
git commit -m "feat: add regulatory source adapters"
```

---

### Task 6: Ethical company-site crawling primitives and page adapter

**Files:**
- Create: `src/impurity_leads/crawling/__init__.py`
- Create: `src/impurity_leads/crawling/robots.py`
- Create: `src/impurity_leads/crawling/fetch.py`
- Create: `src/impurity_leads/crawling/sitemap.py`
- Create: `src/impurity_leads/adapters/company_site.py`
- Create: `tests/fixtures/company_job.html`
- Create: `tests/fixtures/company_pipeline.html`
- Create: `tests/fixtures/impurity_vendor.html`
- Create: `tests/crawling/test_robots.py`
- Create: `tests/crawling/test_sitemap.py`
- Create: `tests/adapters/test_company_site.py`

**Interfaces:**
- Produces: `RobotsPolicy.can_fetch(url) -> bool`, `HttpFetcher.fetch(url) -> str | None`, `extract_sitemap_urls(xml) -> list[str]`, `CompanySiteAdapter.parse_html(url, html, company_name, molecule_candidates) -> list[SourceRecord]`.

- [ ] **Step 1: Write failing robots, sitemap, and company-page tests**

```python
# tests/crawling/test_sitemap.py
from impurity_leads.crawling.sitemap import extract_sitemap_urls


def test_extracts_loc_values():
    xml = "<urlset xmlns='http://www.sitemaps.org/schemas/sitemap/0.9'><url><loc>https://example.com/jobs</loc></url></urlset>"
    assert extract_sitemap_urls(xml) == ["https://example.com/jobs"]
```

```python
# tests/adapters/test_company_site.py
from pathlib import Path
from impurity_leads.adapters.company_site import CompanySiteAdapter


def test_job_page_emits_impurity_signal_for_known_molecule():
    html = Path("tests/fixtures/company_job.html").read_text()
    records = CompanySiteAdapter().parse_html("https://example.com/jobs/1", html, "Example Pharma", ["Drug X"])
    assert records
    assert records[0].molecule_name_raw == "Drug X"


def test_vendor_page_is_marked_for_exclusion():
    html = Path("tests/fixtures/impurity_vendor.html").read_text()
    records = CompanySiteAdapter().parse_html("https://vendor.example/services", html, "Vendor Labs", [])
    assert records[0].metadata_json["is_impurity_vendor"] is True
```

- [ ] **Step 2: Run crawling tests and verify failures**

Run: `python -m pytest tests/crawling tests/adapters/test_company_site.py -v`
Expected: FAIL because modules do not exist.

- [ ] **Step 3: Implement robots-aware fetch, sitemap parser, and focused HTML extraction**

`RobotsPolicy` must use Python's `urllib.robotparser.RobotFileParser` and the configured User-Agent. `HttpFetcher` must use `httpx.Client(follow_redirects=True)`, maximum two retries for network errors/5xx, honor `Retry-After` when present, and return `None` on denied/blocked access rather than attempting evasion. `CompanySiteAdapter` must parse visible text with BeautifulSoup, identify known molecule names by case-insensitive literal matching, classify impurity phrases, and return short evidence windows only.

- [ ] **Step 4: Run crawling tests**

Run: `python -m pytest tests/crawling tests/adapters/test_company_site.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/impurity_leads/crawling src/impurity_leads/adapters/company_site.py tests/crawling tests/adapters/test_company_site.py tests/fixtures/company_job.html tests/fixtures/company_pipeline.html tests/fixtures/impurity_vendor.html
git commit -m "feat: crawl company sites safely"
```

---

### Task 7: Targeted Common Crawl discovery adapter

**Files:**
- Create: `src/impurity_leads/adapters/common_crawl.py`
- Create: `tests/adapters/test_common_crawl.py`

**Interfaces:**
- Produces: `filter_index_records(records: list[dict], domain: str) -> list[dict]`, `CommonCrawlAdapter.discover(domain: str, url_terms: tuple[str, ...]) -> list[str]`.

- [ ] **Step 1: Write failing URL-filter test**

```python
# tests/adapters/test_common_crawl.py
from impurity_leads.adapters.common_crawl import filter_index_records


def test_filters_to_relevant_same_domain_urls():
    records = [
        {"url": "https://example.com/careers/analytical-scientist"},
        {"url": "https://example.com/privacy"},
        {"url": "https://other.com/careers"},
    ]
    urls = filter_index_records(records, "example.com")
    assert urls == [{"url": "https://example.com/careers/analytical-scientist"}]
```

- [ ] **Step 2: Run test and verify failure**

Run: `python -m pytest tests/adapters/test_common_crawl.py -v`
Expected: FAIL because module does not exist.

- [ ] **Step 3: Implement targeted index querying only**

The adapter must query a configured Common Crawl index endpoint with a domain pattern, parse JSON-lines index responses, retain only same-domain URLs matching one of these path terms: `career`, `job`, `pipeline`, `research`, `press`, `news`, `procurement`, `tender`, `impurity`, `nitrosamine`, `stability`, `analytical`. It must cap returned URLs per domain so one site cannot exhaust the GitHub Actions budget.

- [ ] **Step 4: Run adapter test**

Run: `python -m pytest tests/adapters/test_common_crawl.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/impurity_leads/adapters/common_crawl.py tests/adapters/test_common_crawl.py
git commit -m "feat: add common crawl discovery"
```

---

### Task 8: Pipeline orchestration and in-memory persistence

**Files:**
- Create: `src/impurity_leads/storage/__init__.py`
- Create: `src/impurity_leads/storage/base.py`
- Create: `src/impurity_leads/storage/memory.py`
- Create: `src/impurity_leads/pipeline.py`
- Create: `tests/test_pipeline.py`

**Interfaces:**
- Produces: `LeadStore` protocol, `MemoryLeadStore`, `process_records(records: list[SourceRecord], store: LeadStore) -> list[Opportunity]`.

- [ ] **Step 1: Write failing end-to-end fixture pipeline test**

```python
# tests/test_pipeline.py
from datetime import datetime, timezone
from impurity_leads.models import SourceRecord
from impurity_leads.pipeline import process_records
from impurity_leads.storage.memory import MemoryLeadStore


def test_pipeline_creates_opportunity_from_multiple_signals():
    now = datetime.now(timezone.utc)
    records = [
        SourceRecord(source_name="trial", source_type="trial", source_url="https://a", fetched_at=now, company_name_raw="Example Pharma", molecule_name_raw="Drug X", signal_text="Phase III small molecule program", metadata_json={"phase": "PHASE3"}),
        SourceRecord(source_name="site", source_type="job", source_url="https://b", fetched_at=now, company_name_raw="Example Pharma", molecule_name_raw="Drug X", signal_text="impurity characterization and forced degradation for Drug X"),
    ]
    store = MemoryLeadStore()
    opportunities = process_records(records, store)
    assert opportunities
    assert store.signals
    assert store.opportunities
```

- [ ] **Step 2: Run test and verify failure**

Run: `python -m pytest tests/test_pipeline.py -v`
Expected: FAIL because pipeline/storage modules do not exist.

- [ ] **Step 3: Implement normalization -> classification -> fingerprint -> aggregation flow**

`process_records` must normalize company/molecule names, detect vendor exclusion before qualification, create one `Signal` per matched deterministic rule, add Phase II/III regulatory/development signals from metadata, deduplicate by fingerprint, save structured signals, aggregate opportunities, and save qualified opportunities. It must never persist the original full HTML/body because `SourceRecord` contains only compact `signal_text`.

- [ ] **Step 4: Run pipeline test**

Run: `python -m pytest tests/test_pipeline.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/impurity_leads/storage src/impurity_leads/pipeline.py tests/test_pipeline.py
git commit -m "feat: orchestrate lead pipeline"
```

---

### Task 9: CSV and Excel opportunity exports

**Files:**
- Create: `src/impurity_leads/export.py`
- Create: `tests/test_export.py`

**Interfaces:**
- Produces: `export_csv(opportunities, path) -> Path`, `export_xlsx(opportunities, path) -> Path`.

- [ ] **Step 1: Write failing export tests**

```python
# tests/test_export.py
from impurity_leads.export import export_csv, export_xlsx
from impurity_leads.models import Opportunity


def test_exports_csv_and_xlsx(tmp_path):
    opportunity = Opportunity(company_name="Example Pharma", molecule_name="Drug X", score=80, priority="HOT", rationale="nitrosamine", likely_need_type=["nitrosamine/NDSRI"], decision_maker_role=["Analytical Development"], signal_fingerprints=["abc"])
    csv_path = export_csv([opportunity], tmp_path / "opportunities.csv")
    xlsx_path = export_xlsx([opportunity], tmp_path / "opportunities.xlsx")
    assert csv_path.exists()
    assert xlsx_path.exists()
```

- [ ] **Step 2: Run test and verify failure**

Run: `python -m pytest tests/test_export.py -v`
Expected: FAIL because export module does not exist.

- [ ] **Step 3: Implement stable export columns**

CSV/XLSX headers must include at minimum `Date`, `Priority`, `Score`, `Company`, `Molecule/API`, `Likely Need`, `Why Now`, `Recommended Role 1`, `Recommended Role 2`, `Signal Count`, and `Last Seen`. XLSX must use `openpyxl` and freeze the first row; no styling beyond basic bold headers is required.

- [ ] **Step 4: Run export test**

Run: `python -m pytest tests/test_export.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/impurity_leads/export.py tests/test_export.py
git commit -m "feat: export qualified opportunities"
```

---

### Task 10: Supabase schema, RLS, and storage adapter

**Files:**
- Create: `supabase/schema.sql`
- Create: `src/impurity_leads/storage/supabase_store.py`
- Create: `tests/test_supabase_store.py`

**Interfaces:**
- Produces: `SupabaseLeadStore` implementing `LeadStore`.
- Database tables: `companies`, `molecules`, `company_molecules`, `signals`, `opportunities`, `opportunity_signals`, `crawl_runs`, `crawl_domains`.

- [ ] **Step 1: Write failing storage-adapter unit test using a fake Supabase client**

```python
# tests/test_supabase_store.py
from impurity_leads.storage.supabase_store import SupabaseLeadStore


class FakeTable:
    def __init__(self):
        self.rows = []
    def upsert(self, row, **kwargs):
        self.rows.append(row)
        return self
    def execute(self):
        return type("Result", (), {"data": self.rows})()


class FakeClient:
    def __init__(self):
        self.tables = {}
    def table(self, name):
        self.tables.setdefault(name, FakeTable())
        return self.tables[name]


def test_store_writes_signal_without_raw_html():
    client = FakeClient()
    store = SupabaseLeadStore(client)
    store.save_signal_dict({"fingerprint": "abc", "evidence_text": "compact evidence"})
    assert client.tables["signals"].rows[0]["fingerprint"] == "abc"
    assert "html" not in client.tables["signals"].rows[0]
```

- [ ] **Step 2: Run test and verify failure**

Run: `python -m pytest tests/test_supabase_store.py -v`
Expected: FAIL because the Supabase storage adapter does not exist.

- [ ] **Step 3: Implement schema with explicit grants and RLS**

`supabase/schema.sql` must:

- create all eight tables from the design using UUID primary keys and appropriate foreign keys/indexes;
- make `signals.fingerprint` unique;
- enable RLS on every table;
- revoke all table access from `anon`;
- grant `SELECT` on lead/intelligence tables to `authenticated`;
- grant only the dashboard-required `UPDATE` columns/tables to `authenticated` (opportunity review status/notes when added);
- grant crawler server-side write access through the Supabase secret-key role only;
- avoid `SECURITY DEFINER` functions;
- use `security_invoker = true` for any exposed views;
- include indexes on `signals(company_id, molecule_id, event_date)`, `opportunities(priority, score)`, and `crawl_domains(next_crawl_at)`.

- [ ] **Step 4: Implement `SupabaseLeadStore` using the current Supabase Python client**

The store receives an already-created client so tests do not need credentials. Upserts must use natural/unique keys where defined and send only structured fields from Pydantic models.

- [ ] **Step 5: Run unit test**

Run: `python -m pytest tests/test_supabase_store.py -v`
Expected: PASS.

- [ ] **Step 6: Review schema against current Supabase docs before applying it**

Verify current RLS, grants, and key guidance with the Supabase documentation. Do not apply `schema.sql` to the connected project in this step.

- [ ] **Step 7: Commit**

```bash
git add supabase/schema.sql src/impurity_leads/storage/supabase_store.py tests/test_supabase_store.py
git commit -m "feat: add secure supabase persistence"
```

---

### Task 11: CLI and daily-run script with execution budget guardrail

**Files:**
- Create: `src/impurity_leads/cli.py`
- Create: `scripts/run_daily.py`
- Create: `tests/test_cli.py`

**Interfaces:**
- Produces CLI commands: `impurity-leads test-fixtures`, `impurity-leads export`, `impurity-leads run-daily`.

- [ ] **Step 1: Write failing CLI budget test**

```python
# tests/test_cli.py
from impurity_leads.cli import seconds_remaining


def test_budget_guard_returns_zero_after_deadline():
    assert seconds_remaining(start_monotonic=0.0, now_monotonic=60.0, deadline_minutes=1) == 0.0
```

- [ ] **Step 2: Run test and verify failure**

Run: `python -m pytest tests/test_cli.py -v`
Expected: FAIL because CLI module does not exist.

- [ ] **Step 3: Implement CLI and deadline-aware adapter ordering**

`run-daily` must execute sources in this order: Tier 1 regulatory/trials, already-hot known company domains, newly discovered molecules, company sites/jobs, Common Crawl enrichment. It must stop scheduling new work when the configured deadline is reached and still persist a run summary/export for completed work.

- [ ] **Step 4: Run CLI test**

Run: `python -m pytest tests/test_cli.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/impurity_leads/cli.py scripts/run_daily.py tests/test_cli.py
git commit -m "feat: add daily crawl command"
```

---

### Task 12: CI and zero-cost daily GitHub Actions workflow

**Files:**
- Create: `.github/workflows/test.yml`
- Create: `.github/workflows/daily-crawl.yml`
- Modify: `README.md`

**Interfaces:**
- Produces: automated test workflow and one scheduled daily production crawl.

- [ ] **Step 1: Create test workflow**

```yaml
# .github/workflows/test.yml
name: tests
on:
  push:
  pull_request:

jobs:
  pytest:
    runs-on: ubuntu-latest
    timeout-minutes: 15
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: pip
      - run: python -m pip install -e '.[dev]'
      - run: python -m pytest -q
```

- [ ] **Step 2: Create daily workflow with hard timeout and secrets**

```yaml
# .github/workflows/daily-crawl.yml
name: daily impurity lead crawl
on:
  schedule:
    - cron: "17 1 * * *"
  workflow_dispatch:

jobs:
  crawl:
    runs-on: ubuntu-latest
    timeout-minutes: 45
    permissions:
      contents: read
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: pip
      - run: python -m pip install .
      - run: python scripts/run_daily.py
        env:
          SUPABASE_URL: ${{ secrets.SUPABASE_URL }}
          SUPABASE_SECRET_KEY: ${{ secrets.SUPABASE_SECRET_KEY }}
          CRAWLER_USER_AGENT: ${{ secrets.CRAWLER_USER_AGENT }}
      - uses: actions/upload-artifact@v4
        if: always()
        with:
          name: daily-opportunity-export
          path: exports/
          retention-days: 7
```

- [ ] **Step 3: Document local setup, free-tier guardrails, ethics, and production secrets in README**

The README must state that the crawler is public-web-only, obeys robots.txt, does not bypass anti-bot protections, does not use paid APIs, and does not store raw HTML. It must document `pip install -e '.[dev]'`, `pytest`, local fixture execution, and required GitHub secrets.

- [ ] **Step 4: Run complete local test suite**

Run: `python -m pytest -q`
Expected: all tests PASS.

- [ ] **Step 5: Run a local fixture smoke test**

Run: `python -m impurity_leads.cli test-fixtures`
Expected: at least one qualified molecule-level opportunity is printed and exported without live network access.

- [ ] **Step 6: Commit**

```bash
git add .github README.md
git commit -m "ci: add zero-cost scheduled pipeline"
```

---

### Task 13: Pre-production verification checkpoint

**Files:**
- Review only; no production change yet.

**Interfaces:**
- Produces: verified repository ready for the user's requested final-change approval.

- [ ] **Step 1: Run all tests from a clean environment**

Run:

```bash
python -m pip install -e '.[dev]'
python -m pytest -q
```

Expected: all tests PASS.

- [ ] **Step 2: Inspect for raw-page persistence and secret exposure**

Run:

```bash
grep -RniE 'raw_html|full_html|service_role|SUPABASE_SECRET_KEY=' src supabase .github README.md || true
```

Expected: no raw-page persistence fields; secret key appears only as an environment-variable name or GitHub secret reference, never as a literal credential.

- [ ] **Step 3: Verify schema security locally/by review**

Confirm every exposed table has `ENABLE ROW LEVEL SECURITY`, `anon` has no table grants, and browser-facing reads require `authenticated`.

- [ ] **Step 4: Report the final-change checkpoint to the user**

Before applying `supabase/schema.sql` to `Ravi Project`, before adding any GitHub repository secrets, and before enabling the scheduled production crawl, show the user:

1. tests and smoke-test results;
2. exact Supabase objects that will be created;
3. exact GitHub secrets/workflow behavior;
4. confirmation that projected monthly service cost remains ₹0 under the documented free-tier assumptions.

Do not perform those final production changes until the user approves them.
