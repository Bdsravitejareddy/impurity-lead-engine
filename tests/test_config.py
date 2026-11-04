from impurity_leads.config import load_settings


def test_empty_environment_values_fall_back_to_safe_defaults(monkeypatch):
    monkeypatch.setenv("CRAWLER_USER_AGENT", "")
    monkeypatch.setenv("SUPABASE_URL", "")
    monkeypatch.setenv("SUPABASE_SECRET_KEY", "")
    settings = load_settings()
    assert settings.user_agent == "SVAK-Impurity-Lead-Research/0.1"
    assert settings.supabase_url is None
    assert settings.supabase_secret_key is None


def test_molecule_discovery_settings_load_from_plain_env_names(monkeypatch):
    from impurity_leads.config import load_settings
    monkeypatch.setenv("MOLECULE_DISCOVERY_ENABLED", "true")
    monkeypatch.setenv("PATENTSVIEW_API_KEY", "free-key")
    settings = load_settings()
    assert settings.molecule_discovery_enabled is True
    assert settings.patentsview_api_key == "free-key"
    assert "free-key" not in repr(settings)
