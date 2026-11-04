import json
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

from impurity_leads.contact_quality import score_contact
from impurity_leads.molecule_discovery import (
    OpportunityTarget,
    PoliteFetcher,
    affiliation_matches,
    company_tokens,
    discover_for_opportunity,
    molecule_names,
    orcid_positions,
    patent_people,
    patentsview_url,
    persist_opportunity,
    publication_people,
    run_molecule_discovery,
)
from impurity_leads.zero_cost import ProviderUsage, provider_for_url

FIXTURES = Path(__file__).parent / "fixtures" / "molecule_discovery"
RECORDED = json.loads((FIXTURES / "responses.json").read_text())
PATENTS = json.loads((FIXTURES / "patentsview_sitagliptin.json").read_text())
TODAY = "2026-11-04"

MERCK = OpportunityTarget("opp-merck", "company-merck", "Merck & Co., Inc.", "Sitagliptin", priority="HOT", score=92)
AZ = OpportunityTarget("opp-az", "company-az", "AstraZeneca PLC", "Olaparib", priority="HIGH", score=80)
LUPIN = OpportunityTarget("opp-lupin", "company-lupin", "Lupin Limited", "Varenicline", priority="HIGH", score=78)
ZYDUS = OpportunityTarget("opp-zydus", "company-zydus", "Zydus Lifesciences Limited", "Riociguat", priority="HIGH", score=76)
TORRENT = OpportunityTarget("opp-torrent", "company-torrent", "Torrent Pharmaceuticals Limited", "Atorvastatin", priority="HIGH", score=75)


def replay(extra=None):
    """Recorded responses only: an unrecorded URL fails instead of going live."""
    responses = {**RECORDED, **(extra or {})}
    calls = []

    def fetch(url, headers):
        calls.append((url, headers))
        if url not in responses:
            raise AssertionError(f"unrecorded request: {url}")
        return responses[url]

    fetch.calls = calls
    return fetch


def fetcher(extra=None, **kwargs):
    raw = replay(extra)
    polite = PoliteFetcher(raw, user_agent="test-agent", delay_seconds=0, sleep=lambda _: None, **kwargs)
    polite.raw = raw
    return polite


# --- matching ---------------------------------------------------------------


def test_company_tokens_drop_legal_and_generic_words():
    assert company_tokens("Dr. Reddy's Laboratories Limited") == ["reddy"]
    assert company_tokens("Merck & Co., Inc.") == ["merck"]
    assert company_tokens("Mylan Laboratories Limited (Viatris-associated legacy entity)") == ["mylan"]
    assert company_tokens("Richter Gedeon Nyrt") == ["richter", "gedeon"]


def test_affiliation_match_needs_every_distinctive_word():
    assert affiliation_matches("Analytical R&D, Dr. Reddy's Laboratories Ltd., Hyderabad", "Dr. Reddy's Laboratories Limited")
    assert affiliation_matches("Gedeon Richter Plc., Budapest", "Richter Gedeon Nyrt")
    assert not affiliation_matches("Richter Institute, Budapest", "Richter Gedeon Nyrt")
    assert not affiliation_matches("Department of Chemistry, University of Mumbai", "Lupin Limited")
    assert not affiliation_matches(None, "Lupin Limited")


def test_molecule_names_strip_salts_and_split_combinations():
    assert molecule_names("Fesoterodine fumarate") == ["Fesoterodine"]
    assert molecule_names("Trifluridine / Tipiracil") == ["Trifluridine", "Tipiracil"]
    assert molecule_names("Sitagliptin", ["sitagliptin phosphate", "MK-0431"]) == ["Sitagliptin", "MK-0431"]


# --- Europe PMC -------------------------------------------------------------


def test_molecule_papers_keep_only_company_authors_with_publication_date():
    result = discover_for_opportunity(MERCK, fetcher(), today=TODAY)
    people = {person.name: person for person, _ in result["people"]}
    assert result["errors"] == {}
    assert len(people) == 11
    zheng = people["Jinjian Zheng"]
    assert zheng.molecule_match
    assert zheng.department == "Analytical Chemistry in Development and Supply, MMD"
    assert zheng.email == "jinjian.zheng@merck.com"  # printed in the paper's own affiliation
    paper = zheng.evidence[0]
    assert paper.kind == "PUBLICATION" and paper.source_date == "2024-09-25"
    assert paper.url == "https://europepmc.org/article/MED/39342733"
    # Every author kept is affiliated with Merck in the record itself.
    assert all("merck" in person.evidence[0].detail["affiliation"].casefold() for person in people.values())


def test_paper_without_impurity_terms_or_with_former_affiliation_is_ignored():
    author = {"fullName": "Doe J", "firstName": "Jane", "lastName": "Doe",
              "authorAffiliationDetailsList": {"authorAffiliation": [{"affiliation": "Analytical R&D, Merck & Co., Inc., Rahway, NJ"}]}}
    former = {**author, "firstName": "John", "lastName": "Roe", "fullName": "Roe J",
              "authorAffiliationDetailsList": {"authorAffiliation": [{"affiliation": "Formerly of Analytical R&D, Merck & Co., Inc., Rahway, NJ"}]}}
    paper = {"pmid": "1", "title": "Sitagliptin impurity profiling", "firstPublicationDate": "2025-01-02", "authorList": {"author": [author, former]}}
    assert [person.name for person in publication_people(paper, MERCK)] == ["Jane Doe"]
    assert publication_people({**paper, "title": "Sitagliptin pharmacokinetics"}, MERCK) == []
    assert publication_people({**paper, "title": "Metformin impurity profiling"}, MERCK) == []


def test_company_tier_fills_in_when_molecule_work_is_absent_and_is_capped():
    result = discover_for_opportunity(LUPIN, fetcher(), today=TODAY)
    people = [person for person, _ in result["people"]]
    assert 0 < len(people) <= 5
    assert not any(person.molecule_match for person in people)
    assert all(person.evidence[0].detail["impurity_terms"] for person in people)


def test_opportunity_with_no_public_work_finds_nobody():
    result = discover_for_opportunity(TORRENT, fetcher(), today=TODAY)
    assert result["people"] == [] and result["errors"] == {}


# --- ORCID ------------------------------------------------------------------


def test_orcid_confirms_current_employer_and_title_with_dates():
    result = discover_for_opportunity(AZ, fetcher(), today=TODAY)
    people = {person.name: person for person, _ in result["people"]}
    ashworth = people["Ian W Ashworth"]
    assert ashworth.employment == "ORCID_CURRENT"
    assert ashworth.title == "Principal Scientist"
    # His AstraZeneca employment is undated on ORCID; the record's own
    # last-modified date is the source date, never the crawl date.
    current = [row for row in ashworth.positions if row.end_date is None]
    assert current[0].company_name == "AstraZeneca PLC" and current[0].date_precision == "NONE"
    orcid = next(item for item in ashworth.evidence if item.kind == "ORCID_EMPLOYMENT")
    assert orcid.url == "https://orcid.org/" + ashworth.orcid
    assert orcid.source_date == "2023-01-09" and orcid.detail["date_basis"] == "last-modified-date"
    # Ranked first: current employment confirmed plus an analytical-chemistry function.
    assert result["people"][0][0] is ashworth


def test_orcid_record_showing_employment_ended_is_marked_and_not_current():
    payload = {"last-modified-date": {"value": 1730000000000}, "affiliation-group": [{"summaries": [{"employment-summary": {
        "role-title": "Senior Manager", "department-name": "ADL", "organization": {"name": "Lupin Limited"},
        "start-date": {"year": {"value": "2015"}, "month": {"value": "04"}}, "end-date": {"year": {"value": "2021"}}}}]}]}
    positions, as_of = orcid_positions(payload, "Lupin Limited")
    assert as_of == "2024-10-27"
    assert positions[0].start_date == "2015-04-01" and positions[0].date_precision == "MONTH"
    assert positions[0].end_date == "2021-01-01"
    assert orcid_positions(payload, "Cipla Limited")[0] == []


# --- PatentsView -------------------------------------------------------------


def test_patent_inventors_need_company_assignee_molecule_and_process_terms():
    people = [person for patent in PATENTS["patents"] for person in patent_people(patent, MERCK)]
    assert [person.name for person in people] == ["Example Inventorone", "Jinjian Zheng"]
    evidence = people[0].evidence[0]
    assert evidence.source_date == "2022-06-14"  # filing date: when the inventor did the work
    assert evidence.detail["date_basis"] == "application.filing_date"


def test_patent_and_paper_evidence_merge_into_one_person():
    result = discover_for_opportunity(MERCK, fetcher({patentsview_url(MERCK): PATENTS}), patentsview_api_key="k", today=TODAY)
    people = {person.name: person for person, _ in result["people"]}
    assert {item.kind for item in people["Jinjian Zheng"].evidence} == {"PUBLICATION", "PATENT"}
    assert "Example Inventorone" in people


def test_patentsview_is_called_with_key_header_only_when_configured():
    polite = fetcher({patentsview_url(MERCK): PATENTS})
    discover_for_opportunity(MERCK, polite, patentsview_api_key="secret", today=TODAY)
    patent_calls = [headers for url, headers in polite.raw.calls if "patentsview" in url]
    assert patent_calls and patent_calls[0]["X-Api-Key"] == "secret"
    plain = fetcher()
    discover_for_opportunity(MERCK, plain, today=TODAY)
    assert not any("patentsview" in url for url, _ in plain.raw.calls)


# --- politeness and accounting -------------------------------------------------


def test_polite_fetcher_throttles_per_host_budgets_and_records_usage():
    sleeps, now = [], [0.0]
    usage = ProviderUsage()
    polite = PoliteFetcher(lambda url, headers: {"ua": headers["User-Agent"]}, user_agent="ua/1", delay_seconds=1.0,
                           max_requests=3, usage=usage, sleep=sleeps.append, clock=lambda: now[0])
    polite("https://www.ebi.ac.uk/europepmc/webservices/rest/search?q=1")
    now[0] = 0.25
    polite("https://www.ebi.ac.uk/europepmc/webservices/rest/search?q=2")
    polite("https://pub.orcid.org/v3.0/0000/employments")
    assert sleeps == [0.75]  # second Europe PMC call waits; ORCID is another host
    with pytest.raises(RuntimeError, match="budget"):
        polite("https://pub.orcid.org/v3.0/0001/employments")
    assert {row["provider"]: row["requests"] for row in usage.rows()} == {"europe_pmc": 2, "orcid": 1}
    assert provider_for_url("https://search.patentsview.org/api/v1/patent/") == "patentsview"


# --- persistence -------------------------------------------------------------


class _Result:
    def __init__(self, data):
        self.data = data


class _Query:
    def __init__(self, table, action="select", payload=None, on_conflict=None):
        self.table, self.action, self.payload, self.on_conflict, self.filters = table, action, payload, on_conflict, []
        self._limit = None

    def select(self, *_):
        return self

    def eq(self, key, value):
        self.filters.append(lambda row: row.get(key) == value)
        return self

    def neq(self, key, value):
        self.filters.append(lambda row: row.get(key) != value)
        return self

    def in_(self, key, values):
        self.filters.append(lambda row: row.get(key) in values)
        return self

    def order(self, *_args, **_kwargs):
        return self

    def limit(self, value):
        self._limit = value
        return self

    def execute(self):
        rows = self.table.rows
        if self.action == "insert":
            row = {"id": f"{self.table.name}-{len(rows) + 1}", **self.payload}
            rows.append(row)
            return _Result([row])
        if self.action == "upsert":
            keys = [key.strip() for key in (self.on_conflict or "").split(",") if key.strip()]
            existing = next((row for row in rows if keys and all(row.get(key) == self.payload.get(key) for key in keys)), None)
            if existing:
                existing.update(self.payload)
                return _Result([existing])
            row = {"id": f"{self.table.name}-{len(rows) + 1}", **self.payload}
            rows.append(row)
            return _Result([row])
        matched = [row for row in rows if all(check(row) for check in self.filters)]
        if self.action == "update":
            for row in matched:
                row.update(self.payload)
            return _Result(matched)
        return _Result(matched[: self._limit] if self._limit else matched)


class _Table:
    def __init__(self, name, rows=None):
        self.name, self.rows = name, rows or []

    def select(self, *_):
        return _Query(self)

    def insert(self, payload):
        return _Query(self, "insert", payload)

    def upsert(self, payload, on_conflict=None):
        return _Query(self, "upsert", payload, on_conflict)

    def update(self, payload):
        return _Query(self, "update", payload)


class _Client:
    def __init__(self, **tables):
        self.tables = {name: _Table(name, rows) for name, rows in tables.items()}

    def table(self, name):
        return self.tables.setdefault(name, _Table(name))


def _sources_for(client, contact_id):
    return [row for row in client.tables["contact_sources"].rows if row["contact_id"] == contact_id]


def test_persisted_contacts_have_dated_sources_so_role_is_source_dated():
    client = _Client()
    metrics = persist_opportunity(client, discover_for_opportunity(MERCK, fetcher(), today=TODAY))
    assert metrics["new_contacts"] == 11 and metrics["links"] == 3
    contacts = client.tables["contacts"].rows
    zheng = next(row for row in contacts if row["display_name"] == "Jinjian Zheng")
    assert zheng["email_status"] == "VERIFIED_PUBLIC" and zheng["company_id"] == "company-merck"
    sources = _sources_for(client, zheng["id"])
    assert sources[0]["source_date"] == "2024-09-25"
    assert sources[0]["source_kind"] == "MOLECULE_DISCOVERY" and sources[0]["status"] == "USED"
    assert sources[0]["extraction_json"]["attribution"] == "PERSON_DIRECT"
    for contact in contacts:
        scored = score_contact(contact, sources=_sources_for(client, contact["id"]), today=date(2026, 11, 4))
        assert scored["basis"]["current_role"] == "SOURCE_DATED"
        assert scored["basis"]["recency"] == "SOURCE_DATED"
    works = client.tables["contact_works"].rows
    assert len(works) == 11 and all(row["attribution"] == "PERSON_DIRECT" and row["molecules"] == ["Sitagliptin"] for row in works)
    links = client.tables["opportunity_contacts"].rows
    assert sorted(row["rank"] for row in links) == [1, 2, 3]
    assert all(row["source_ids"] for row in links)


def test_orcid_positions_are_stored_with_real_dates():
    client = _Client()
    persist_opportunity(client, discover_for_opportunity(ZYDUS, fetcher(), today=TODAY))
    positions = client.tables["contact_positions"].rows
    dated = [row for row in positions if row["start_date"]]
    assert len(dated) >= 3 and all(row["attribution"] == "PERSON_DIRECT" and row["source_ids"] for row in dated)
    assert any(row["end_date"] is None for row in dated)
    titled = [row for row in client.tables["contacts"].rows if row.get("title")]
    assert titled and all(float(row["contact_confidence"]) >= 0.76 for row in titled)


def test_orcid_title_reaches_the_contact():
    client = _Client()
    persist_opportunity(client, discover_for_opportunity(AZ, fetcher(), today=TODAY))
    ashworth = next(row for row in client.tables["contacts"].rows if row["display_name"] == "Ian W Ashworth")
    assert ashworth["title"] == "Principal Scientist" and float(ashworth["contact_confidence"]) >= 0.86
    orcid_source = next(row for row in _sources_for(client, ashworth["id"]) if row["source_type"] == "ORCID record")
    assert orcid_source["source_date"] == "2023-01-09"


def test_existing_contact_is_reused_and_manual_fields_kept():
    existing = {"id": "c-1", "company_id": "company-merck", "normalized_name": "jinjian zheng", "display_name": "Jinjian Zheng",
                "title": "Director, Analytical R&D", "department": None, "primary_email": None, "contact_confidence": 0.5}
    client = _Client(contacts=[existing])
    persist_opportunity(client, discover_for_opportunity(MERCK, fetcher(), today=TODAY))
    zheng_rows = [row for row in client.tables["contacts"].rows if row["normalized_name"] == "jinjian zheng"]
    assert len(zheng_rows) == 1
    assert zheng_rows[0]["title"] == "Director, Analytical R&D"
    assert zheng_rows[0]["primary_email"] == "jinjian.zheng@merck.com"
    assert zheng_rows[0]["contact_confidence"] > 0.5
    # A second run adds no duplicate works or sources.
    before = (len(client.tables["contact_works"].rows), len(client.tables["contact_sources"].rows))
    persist_opportunity(client, discover_for_opportunity(MERCK, fetcher(), today=TODAY))
    assert (len(client.tables["contact_works"].rows), len(client.tables["contact_sources"].rows)) == before


def test_people_who_left_per_orcid_are_kept_but_not_linked():
    client = _Client()
    result = discover_for_opportunity(LUPIN, fetcher(), today=TODAY)
    ended = [person for person, _ in result["people"] if person.employment == "ORCID_ENDED"]
    persist_opportunity(client, result)
    linked = {row["contact_id"] for row in client.tables["opportunity_contacts"].rows}
    by_name = {row["display_name"]: row["id"] for row in client.tables["contacts"].rows}
    assert all(by_name[person.name] not in linked for person in ended)


# --- daily-runner stage -----------------------------------------------------


def _settings(**overrides):
    values = dict(molecule_discovery_enabled=True, molecule_discovery_max_opportunities=10, molecule_discovery_max_papers=10,
                  molecule_discovery_max_requests=200, patentsview_api_key=None, per_domain_delay_seconds=0,
                  user_agent="test-agent", supabase_url=None, supabase_secret_key=None)
    values.update(overrides)
    return SimpleNamespace(**values)


def _seeded_client():
    return _Client(
        opportunities=[
            {"id": "opp-merck", "company_id": "company-merck", "molecule_id": "m-sita", "priority": "HOT", "score": 92, "status": "new"},
            {"id": "opp-torrent", "company_id": "company-torrent", "molecule_id": "m-ator", "priority": "HIGH", "score": 75, "status": "new"},
            {"id": "opp-review", "company_id": "company-merck", "molecule_id": "m-ator", "priority": "REVIEW", "score": 40, "status": "new"},
        ],
        companies=[{"id": "company-merck", "legal_name": "Merck & Co., Inc."}, {"id": "company-torrent", "legal_name": "Torrent Pharmaceuticals Limited"}],
        molecules=[{"id": "m-sita", "canonical_name": "Sitagliptin", "synonyms": []}, {"id": "m-ator", "canonical_name": "Atorvastatin", "synonyms": []}],
    )


def test_stage_is_off_unless_enabled():
    assert run_molecule_discovery(_settings(molecule_discovery_enabled=False))["status"] == "SKIPPED"
    assert run_molecule_discovery(_settings())["reason"] == "supabase_credentials_missing"


def test_stage_processes_hot_high_opportunities_and_reports_per_opportunity():
    usage = ProviderUsage()
    report = run_molecule_discovery(_settings(), client=_seeded_client(), fetch_json=replay(), provider_usage=usage)
    assert report["status"] == "COMPLETED" and report["processed"] == 2
    assert report["patentsview"] == "SKIPPED_NO_KEY"
    per = {row["opportunity_id"]: row for row in report["opportunities"]}
    assert per["opp-merck"]["new_contacts"] == 11 and per["opp-merck"]["links"] == 3
    assert per["opp-torrent"]["new_contacts"] == 0
    assert "opp-review" not in per
    assert {row["provider"] for row in usage.rows()} >= {"europe_pmc"}


def test_stage_stops_cleanly_when_request_budget_is_spent():
    report = run_molecule_discovery(_settings(molecule_discovery_max_requests=1), client=_seeded_client(), fetch_json=replay())
    assert report["status"] == "PARTIAL" and report["stop_reason"] == "request_budget_exhausted"
    assert report["requests"] == 1
