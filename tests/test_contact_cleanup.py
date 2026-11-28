from datetime import datetime, timezone

from impurity_leads.contact_cleanup import contact_fix
from impurity_leads.contacts.extract import extract_contacts_from_html

BIO = ("Dr. Abdelaziz Toumi CEO – Lupin Manufacturing Solutions Abdel is a passionate leader with a blend of "
       "scientific and commercial skills. He brings over 20 years of experience in the biotech, pharma and CDMO sectors.")


def test_headings_are_hidden_and_biographies_cut_to_the_title():
    assert contact_fix({"display_name": "Board of Directors", "title": "Board of Directors Manju D Gupta ..."}) == {"hidden_reason": "not_a_person"}
    assert contact_fix({"display_name": "Key Contacts", "title": None}) == {"hidden_reason": "not_a_person"}
    assert contact_fix({"display_name": "Dr. Abdelaziz Toumi", "title": BIO}) == {"title": "CEO – Lupin Manufacturing Solutions"}
    assert contact_fix({"display_name": "Nilesh D Gupta", "title": "Nilesh D Gupta Managing Director"}) == {"title": "Managing Director"}


def test_clean_rows_and_hidden_rows_are_left_alone():
    assert contact_fix({"display_name": "Ranjana Pathak", "title": "Chief Quality Officer"}) is None
    assert contact_fix({"display_name": "Board of Directors", "hidden_reason": "not_a_person"}) is None


def test_leadership_page_yields_people_with_short_titles():
    html = """<html><body>
    <section class="leadership"><h2>Board of Directors</h2>
      <div class="person"><h3>Nilesh D Gupta</h3><div>Nilesh D Gupta <span>Managing Director</span></div></div>
      <div class="person"><h3>Ranjana Pathak</h3><p>Chief Quality Officer</p>
        <p>Ranjana leads quality across all sites and has over 25 years of experience in quality, regulatory and manufacturing for the director of operations.</p></div>
    </section></body></html>"""
    people = {c.display_name: c.title for c in extract_contacts_from_html("https://example.com/leadership", html, "Example", datetime.now(timezone.utc))}
    assert "Board of Directors" not in people
    assert people == {"Nilesh D Gupta": "Managing Director", "Ranjana Pathak": "Chief Quality Officer"}
