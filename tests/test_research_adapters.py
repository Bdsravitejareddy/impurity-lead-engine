from impurity_leads.research_adapters import classify_source


def test_source_classes_prioritize_primary_domains():
    assert classify_source("https://europepmc.org/article/MED/1")[0] == "PRIMARY"
    assert classify_source("https://www.fda.gov/drugs/example")[1] == "REGULATORY"
    assert classify_source("https://patents.google.com/patent/US1")[1] == "PATENT"


def test_directory_and_professional_sources_are_not_primary():
    assert classify_source("https://rocketreach.co/example")[0] == "DIRECTORY"
    assert classify_source("https://www.linkedin.com/in/example")[0] == "STRONG_PROFESSIONAL"
