from impurity_leads.crawling.robots import RobotsPolicy


def test_robots_policy_denies_disallowed_path():
    policy = RobotsPolicy.from_text(
        "User-agent: *\nDisallow: /private\nAllow: /public\n",
        base_url="https://example.com",
        user_agent="SVAK-Impurity-Lead-Research/0.1",
    )
    assert policy.can_fetch("https://example.com/public/jobs") is True
    assert policy.can_fetch("https://example.com/private/data") is False


def test_robots_policy_reports_crawl_delay_for_our_agent_or_default():
    text = "User-agent: *\nCrawl-delay: 4\n\nUser-agent: SVAK-Impurity-Lead-Research\nCrawl-delay: 7\n"
    assert RobotsPolicy.from_text(text, "https://example.com", "SVAK-Impurity-Lead-Research/0.1").crawl_delay() == 7
    assert RobotsPolicy.from_text(text, "https://example.com", "OtherBot/1.0").crawl_delay() == 4
    assert RobotsPolicy.from_text("User-agent: *\nDisallow:\n", "https://example.com", "x").crawl_delay() is None
    assert RobotsPolicy.from_text("User-agent: *\nRequest-rate: 1/10\n", "https://example.com", "x").crawl_delay() == 10
