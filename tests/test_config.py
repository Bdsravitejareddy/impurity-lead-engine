from impurity_leads.config import load_settings


def test_empty_environment_values_fall_back_to_safe_defaults(monkeypatch):
    monkeypatch.setenv("CRAWLER_USER_AGENT", "")
    monkeypatch.setenv("SUPABASE_URL", "")
    monkeypatch.setenv("SUPABASE_SECRET_KEY", "")
    settings = load_settings()
    assert settings.user_agent == "SVAK-Impurity-Lead-Research/0.1"
    assert settings.supabase_url is None
    assert settings.supabase_secret_key is None
