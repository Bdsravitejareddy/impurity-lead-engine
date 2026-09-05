from impurity_leads.contacts.patterns import detect_email_pattern, generate_pattern_email


def test_requires_two_distinct_named_people_for_pattern():
    assert detect_email_pattern([("Jane Smith", "jane.smith@example.com")], "example.com") is None


def test_detects_consistent_first_dot_last_pattern():
    samples = [
        ("Jane Smith", "jane.smith@example.com"),
        ("Arun Rao", "arun.rao@example.com"),
    ]
    assert detect_email_pattern(samples, "example.com") == "first.last"


def test_conflicting_patterns_disable_inference():
    samples = [
        ("Jane Smith", "jane.smith@example.com"),
        ("Arun Rao", "arao@example.com"),
    ]
    assert detect_email_pattern(samples, "example.com") is None


def test_generic_aliases_never_train_pattern():
    samples = [
        ("Jane Smith", "jane.smith@example.com"),
        ("Sales Team", "sales@example.com"),
    ]
    assert detect_email_pattern(samples, "example.com") is None


def test_generates_pattern_email_but_does_not_validate_mailbox():
    assert generate_pattern_email("Maya Patel", "example.com", "f.last") == "m.patel@example.com"
