import os

from pydantic import BaseModel, Field, model_validator


class Settings(BaseModel):
    user_agent: str = "SVAK-Impurity-Lead-Research/0.1"
    request_timeout_seconds: float = Field(default=20.0, gt=0)
    per_domain_delay_seconds: float = Field(default=1.0, ge=0)
    max_retries: int = 2
    run_deadline_minutes: int = Field(default=42, ge=1)
    workers: int = Field(default=6, ge=1, le=32)
    connect_timeout_seconds: float = Field(default=5.0, gt=0)
    task_timeout_seconds: float = Field(default=300.0, gt=0)
    shutdown_drain_seconds: float = Field(default=30.0, ge=0)
    lease_seconds: int = Field(default=120, ge=10)
    heartbeat_seconds: float = Field(default=20.0, gt=0)
    scheduler_poll_seconds: float = Field(default=0.2, gt=0)
    retry_base_seconds: float = Field(default=5.0, ge=0)
    retry_cap_seconds: float = Field(default=300.0, ge=0)
    domain_cooldown_seconds: float = Field(default=300.0, ge=0)
    outage_window_seconds: float = Field(default=60.0, gt=0)
    outage_domain_threshold: int = Field(default=4, ge=2)
    max_response_bytes: int = Field(default=8 * 1024 * 1024, gt=0)
    supabase_url: str | None = None
    supabase_secret_key: str | None = Field(default=None, repr=False)
    # Production defaults to the no-paid-provider safety boundary. Explicitly
    # set ZERO_COST_MODE=false only for an approved non-production experiment.
    zero_cost_mode: bool = True
    openai_api_key: str | None = Field(default=None, repr=False)
    ai_analysis_enabled: bool = False
    ai_max_calls_per_research_run: int = Field(default=3, ge=0, le=20)
    ai_max_documents_per_run: int = Field(default=5, ge=0, le=50)
    ai_max_people_per_run: int = Field(default=10, ge=0, le=100)
    ai_max_input_chars_per_document: int = Field(default=20000, ge=1000, le=100000)
    ai_max_research_depth: int = Field(default=3, ge=0, le=3)
    ai_web_search_enabled: bool = False
    openai_model_routine: str = "gpt-5.6-luna"
    openai_model_deep: str = "gpt-5.6-sol"
    daily_contact_target: int = Field(default=10, ge=1, le=100)
    min_contact_quality: float = Field(default=70, ge=0, le=100)
    min_identity_confidence: float = Field(default=70, ge=0, le=100)
    min_median_quality: float = Field(default=72, ge=0, le=100)
    min_identity_coverage: float = Field(default=0.80, ge=0, le=1)
    min_technical_coverage: float = Field(default=0.70, ge=0, le=1)
    max_duplicate_rate: float = Field(default=0.15, ge=0, le=1)
    max_ai_search_calls_per_run: int = Field(default=8, ge=0, le=50)
    max_ai_deep_calls_per_run: int = Field(default=3, ge=0, le=20)
    max_research_documents: int = Field(default=30, ge=1, le=200)
    max_research_people: int = Field(default=15, ge=1, le=100)
    min_marginal_quality_gain: float = Field(default=3, ge=0, le=100)


    @model_validator(mode='after')
    def execution_budget(self):
        if self.heartbeat_seconds >= self.lease_seconds / 2:
            raise ValueError('heartbeat must be less than half the lease duration')
        if self.shutdown_drain_seconds >= self.run_deadline_minutes * 60:
            raise ValueError('drain must be shorter than invocation budget')
        return self


def load_settings() -> Settings:
    values = {}
    for name in Settings.model_fields:
        env_name = name.upper() if name.startswith(('supabase_', 'openai_', 'ai_', 'daily_', 'min_', 'max_', 'zero_cost_')) else 'CRAWLER_' + name.upper()
        value = os.getenv(env_name)
        if value:
            values[name] = value
    return Settings.model_validate(values)
