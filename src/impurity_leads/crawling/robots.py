from urllib.parse import urljoin
from urllib.robotparser import RobotFileParser

import httpx


class RobotsPolicy:
    def __init__(self, parser: RobotFileParser, user_agent: str):
        self._parser = parser
        self.user_agent = user_agent
        self.disallow_all = False

    @classmethod
    def from_text(cls, text: str, base_url: str, user_agent: str) -> "RobotsPolicy":
        parser = RobotFileParser()
        parser.set_url(urljoin(base_url.rstrip("/") + "/", "robots.txt"))
        parser.parse(text.splitlines())
        return cls(parser=parser, user_agent=user_agent)

    @classmethod
    def fetch(cls, client, base_url: str, user_agent: str) -> "RobotsPolicy":
        response = client.get(
            f"{base_url.rstrip('/')}/robots.txt", headers={"User-Agent": user_agent}
        )
        status = getattr(response, "status_code", 200)
        if status == 404:
            text = ""
        elif status in {401, 403}:
            text = "User-agent: *\nDisallow: /"
        elif status == 200:
            text = response.text
        else:
            # An unavailable policy is not evidence that crawling is allowed.
            raise httpx.HTTPError(f"robots unavailable status={status}")
        policy = cls.from_text(text, base_url, user_agent)
        policy.disallow_all = status in {401, 403}
        return policy

    def can_fetch(self, url: str) -> bool:
        return self._parser.can_fetch(self.user_agent, url)
