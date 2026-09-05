import os

from pydantic import BaseModel


class Settings(BaseModel):
    user_agent: str = "SVAK-Impurity-Lead-Research/0.1"
    request_timeout_seconds: float = 20.0
    per_domain_delay_seconds: float = 1.0
    max_retries: int = 2
    run_deadline_minutes: int = 42
    supabase_url: str | None = None
    supabase_secret_key: str | None = None


def load_settings() -> Settings:
    return Settings(
        user_agent=os.getenv("CRAWLER_USER_AGENT") or "SVAK-Impurity-Lead-Research/0.1",
        supabase_url=os.getenv("SUPABASE_URL") or None,
        supabase_secret_key=os.getenv("SUPABASE_SECRET_KEY") or None,
    )
