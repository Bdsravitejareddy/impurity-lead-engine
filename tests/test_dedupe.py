from impurity_leads.dedupe import signal_fingerprint


def test_fingerprint_is_stable_for_whitespace_changes():
    first = signal_fingerprint("example pharma", "drug x", "nitrosamine_ndsri", "https://a.com/x", "NDSRI  work")
    second = signal_fingerprint("example pharma", "drug x", "nitrosamine_ndsri", "https://a.com/x", "NDSRI work")
    assert first == second
