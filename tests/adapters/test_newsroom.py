from datetime import datetime, timezone

from impurity_leads.adapters.company_site import CompanySiteAdapter
from impurity_leads.adapters.newsroom import announcement_people, event_types, parse_announcement
from impurity_leads.contacts.extract import extract_contacts_from_html
from impurity_leads.models import SourceRecord
from impurity_leads.pipeline import process_records_with_candidates
from impurity_leads.score import CONTEXT_CAP
from impurity_leads.storage.memory import MemoryLeadStore

URL = "https://www.example-pharma.com/news/2026/example-pharma-receives-usfda-approval-for-ciprofloxacin"
RELEASE = """<html><head><meta property="article:published_time" content="2026-10-15T08:00:00Z"></head>
<body><nav>Home News Careers</nav><article>
<h1>Example Pharma receives USFDA final approval for Ciprofloxacin Tablets</h1>
<p>Mumbai, 15 October 2026. Example Pharma Ltd today announced that it has received final approval from the
United States Food and Drug Administration for its Abbreviated New Drug Application for Ciprofloxacin Tablets USP,
750 mg. The product will be manufactured at the company's Goa facility and launched in the coming quarter.</p>
<p>"This approval strengthens our anti-infective portfolio and reflects the quality of our development teams,"
said Dr. Asha Rao, Chief Scientific Officer at Example Pharma.</p>
<p>Media contact</p><p>Neha Shah</p><p>Head of Corporate Communications</p><p>neha.shah@example-pharma.com</p>
</article><footer>Copyright</footer></body></html>"""
NOW = datetime(2026, 11, 24, tzinfo=timezone.utc)


def test_release_becomes_a_dated_announcement_with_its_people():
    announcement = parse_announcement(URL, RELEASE, datetime(2026, 10, 15, tzinfo=timezone.utc))
    assert announcement is not None
    assert announcement.title.startswith("Example Pharma receives USFDA final approval")
    assert announcement.event_types[0] == "approval"
    people = {person["name"]: person for person in announcement.people}
    assert people["Dr. Asha Rao"]["title"] == "Chief Scientific Officer"
    assert people["Neha Shah"]["email"] == "neha.shah@example-pharma.com"
    assert people["Neha Shah"]["kind"] == "media_contact"


def test_listing_pages_and_non_news_pages_are_not_announcements():
    listing = "<html><body><h1>News</h1><a href='/news/a'>A</a><a href='/news/b'>B</a></body></html>"
    dated = datetime(2026, 10, 15, tzinfo=timezone.utc)
    assert parse_announcement("https://example.com/news", listing, dated) is None
    assert parse_announcement("https://example.com/products/cipro", RELEASE, dated) is None
    undated = RELEASE.replace("Mumbai, 15 October 2026. ", "").replace('<meta property="article:published_time" content="2026-10-15T08:00:00Z">', "")
    assert parse_announcement(URL, undated, None) is None


def test_date_written_in_the_release_text_is_used():
    page = RELEASE.replace('<meta property="article:published_time" content="2026-10-15T08:00:00Z">', "")
    assert parse_announcement(URL, page, None).published_at == datetime(2026, 10, 15, tzinfo=timezone.utc)


def test_clean_inspection_is_not_read_as_a_warning():
    kinds = event_types("U.S. FDA Completes Inspection of Lupin's Dabhasa Facility with No Observations")
    assert "inspection" in kinds and "recall_or_warning" not in kinds


def test_headline_event_leads():
    page = RELEASE.replace("Example Pharma receives USFDA final approval for Ciprofloxacin Tablets",
                           "USFDA completes inspection of Example Pharma's Goa facility")
    announcement = parse_announcement(URL, page, None)
    assert announcement.event_types[0] == "inspection" and "approval" in announcement.event_types


def test_company_name_after_the_title_is_dropped():
    [person] = announcement_people("We are honored, said Tushara Shankar, Head – CSR, Lupin.")
    assert person["title"] == "Head – CSR"


def test_media_block_headings_and_other_peoples_addresses_are_rejected():
    text = "Media Relations\nPress Releases\ninfo@example.com\n"
    assert announcement_people(text) == []
    text = "Media contact\nManjira Sharma\nGeneral Manager – Corporate Communications\nother.person@example.com"
    [person] = announcement_people(text)
    assert person["name"] == "Manjira Sharma" and person["email"] is None


def test_event_types_cover_the_triggers_that_start_impurity_work():
    assert "filing" in event_types("The company has filed an ANDA for apixaban")
    assert "inspection" in event_types("Goa plant completes USFDA inspection with zero observations")
    assert "recall_or_warning" in event_types("Company receives warning letter for its Hyderabad unit")
    assert "facility" in event_types("Example inaugurates new API manufacturing facility in Vizag")


def test_quote_attribution_before_said_is_read():
    people = announcement_people("Rahul Mehta, Vice President of Quality, said the site is ready.")
    assert people == [{"name": "Rahul Mehta", "title": "Vice President of Quality", "email": None, "kind": "quoted"}]


def test_sentence_starts_are_not_taken_for_names():
    assert announcement_people("The Company, a leading manufacturer, said results were strong.") == []


def test_release_adds_a_capped_announcement_signal_per_molecule():
    records = CompanySiteAdapter().parse_html(URL, RELEASE, "Example Pharma Ltd", ["Ciprofloxacin"])
    news = [record for record in records if record.source_type == "news"]
    assert len(news) == 1
    assert news[0].metadata_json["announcement_type"] == "approval"
    assert news[0].published_at == datetime(2026, 10, 15, 8, tzinfo=timezone.utc)
    opportunities, candidates = process_records_with_candidates(news, MemoryLeadStore())
    [candidate] = candidates
    assert candidate["likely_need_type"] == ["company announcement"]
    # Context alone never qualifies a lead as HIGH or HOT.
    assert candidate["priority"] not in {"HOT", "HIGH"} and not opportunities


def test_announcement_without_a_known_molecule_adds_no_signal():
    record = SourceRecord(source_name="company_site", source_type="news", source_url=URL, fetched_at=NOW,
                          company_name_raw="Example Pharma Ltd", signal_text="Example Pharma opens new plant",
                          published_at=NOW, metadata_json={"announcement_type": "facility"})
    opportunities, _ = process_records_with_candidates([record], MemoryLeadStore())
    assert opportunities == [] or all(o.score <= CONTEXT_CAP for o in opportunities)


def test_people_quoted_in_a_release_become_current_role_contacts():
    contacts = extract_contacts_from_html(URL, RELEASE, "Example Pharma Ltd", NOW)
    by_name = {contact.display_name: contact for contact in contacts}
    assert by_name["Dr. Asha Rao"].title == "Chief Scientific Officer"
    assert {item.source_type for item in by_name["Dr. Asha Rao"].evidence} == {"company_press"}
    # The media contact's address is on the company's own domain, so it is published.
    assert by_name["Neha Shah"].primary_email == "neha.shah@example-pharma.com"
    assert by_name["Neha Shah"].email_status == "VERIFIED_PUBLIC"
