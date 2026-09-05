from impurity_leads.crawling.robots import RobotsPolicy


def test_robots_policy_denies_disallowed_path():
    policy = RobotsPolicy.from_text(
        "User-agent: *\nDisallow: /private\nAllow: /public\n",
        base_url="https://example.com",
        user_agent="SVAK-Impurity-Lead-Research/0.1",
    )
    assert policy.can_fetch("https://example.com/public/jobs") is True
    assert policy.can_fetch("https://example.com/private/data") is False
