from impurity_leads.contacts.normalize import (
    email_domain,
    normalize_email,
    normalize_person_name,
    person_name_compatibility,
    title_family,
)


def test_normalize_person_name_strips_honorifics_and_punctuation():
    assert normalize_person_name("Dr. Jane A. Smith") == "jane a smith"


def test_normalize_person_name_strips_academic_suffixes_conservatively():
    assert normalize_person_name("Benjamin Roembke, Ph.D.") == "benjamin roembke"
    assert normalize_person_name("Vijayasarathi Ramaswami") == "vijayasarathi ramaswami"


def test_name_compatibility_supports_initials_but_not_weak_common_name_merges():
    assert person_name_compatibility("Vijayasarathi Ramaswami", "Vijayasarathi R") >= 0.8
    assert person_name_compatibility("Vijayasarathi Ramaswami", "V Ramaswami") >= 0.8
    assert person_name_compatibility("Jitendra Singh", "Jitendra Singh") == 1.0
    assert person_name_compatibility("Jitendra Singh", "Jitendra Kumar") == 0.0


def test_normalize_email_rejects_malformed_and_normalizes_case():
    assert normalize_email(" Jane.Smith@Example.COM ") == "jane.smith@example.com"
    assert normalize_email("not-an-email") is None


def test_email_domain_returns_normalized_domain():
    assert email_domain("Jane.Smith@Example.COM") == "example.com"


def test_title_family_maps_analytical_role():
    assert title_family("Director, Analytical Development") == "analytical"
