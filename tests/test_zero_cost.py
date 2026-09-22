import pytest

from impurity_leads.config import Settings, load_settings
from impurity_leads.zero_cost import PAID_PROVIDERS, ProviderUsage, assert_paid_provider_allowed


def test_zero_cost_mode_is_enabled_by_default_and_can_be_configured(monkeypatch):
    monkeypatch.delenv("ZERO_COST_MODE", raising=False)
    assert Settings().zero_cost_mode is True
    monkeypatch.setenv("ZERO_COST_MODE", "false")
    assert load_settings().zero_cost_mode is False


def test_paid_provider_guard_raises_without_network_call():
    usage = ProviderUsage()
    with pytest.raises(RuntimeError, match="paid_provider_disabled"):
        assert_paid_provider_allowed("openai", Settings(zero_cost_mode=True), usage)
    assert usage.rows() == [{"provider": "openai", "requests": 1, "jobs": 0, "estimated_paid_requests": 1}]


def test_provider_usage_tracks_free_requests_and_jobs_without_paid_cost():
    usage = ProviderUsage()
    usage.record("europe_pmc", requests=3, jobs=2)
    usage.record("chatgpt_work", jobs=1)
    assert usage.rows() == [
        {"provider": "chatgpt_work", "requests": 0, "jobs": 1, "estimated_paid_requests": 0},
        {"provider": "europe_pmc", "requests": 3, "jobs": 2, "estimated_paid_requests": 0},
    ]


def test_openai_adapter_is_hard_blocked_in_zero_cost_mode(monkeypatch):
    from impurity_leads.ai_analysis import analyze_json

    def forbidden(*args, **kwargs):
        raise AssertionError("network must not be reached")

    monkeypatch.setattr("impurity_leads.ai_analysis.urlopen", forbidden)
    with pytest.raises(RuntimeError, match="paid_provider_disabled"):
        analyze_json(
            Settings(zero_cost_mode=True, ai_analysis_enabled=True, openai_api_key="configured"),
            instructions="return json", document="text", schema={"type": "object"},
        )


def test_all_known_paid_provider_names_are_blocked():
    for provider in PAID_PROVIDERS:
        with pytest.raises(RuntimeError, match="paid_provider_disabled"):
            assert_paid_provider_allowed(provider, Settings(zero_cost_mode=True))


def test_public_provider_host_classification_is_not_paid():
    from impurity_leads.zero_cost import provider_for_url

    assert provider_for_url("https://api.fda.gov/drug/drugsfda.json") == "openfda"
    assert provider_for_url("https://index.commoncrawl.org/collinfo.json") == "common_crawl"
    assert provider_for_url("https://patents.google.com/?q=impurity") == "google_patents"
