"""Optional, bounded OpenAI Responses API adapter.

This module is backend-only. It is disabled unless explicitly enabled and a
backend ``OPENAI_API_KEY`` is present. Failures return ``None`` so the
deterministic research pipeline continues normally.
"""
from __future__ import annotations

import json
from urllib.request import Request, urlopen
from typing import Any
from impurity_leads.zero_cost import ProviderUsage, assert_paid_provider_allowed


def analyze_json(settings, *, instructions: str, document: str, schema: dict[str, Any], model: str = "gpt-4o-mini", usage: ProviderUsage | None = None) -> dict[str, Any] | None:
    if not getattr(settings, "ai_analysis_enabled", False) or not getattr(settings, "openai_api_key", None):
        return None
    assert_paid_provider_allowed("openai", settings, usage)
    if usage is not None:
        usage.record("openai", requests=1, estimated_paid_requests=1)
    bounded = document[: int(getattr(settings, "ai_max_input_chars_per_document", 20000))]
    payload = {
        "model": model,
        "input": [{"role": "system", "content": instructions}, {"role": "user", "content": bounded}],
        "text": {"format": {"type": "json_schema", "name": "svak_analysis", "strict": True, "schema": schema}},
    }
    request = Request("https://api.openai.com/v1/responses", data=json.dumps(payload).encode(), method="POST", headers={"Authorization": f"Bearer {settings.openai_api_key}", "Content-Type": "application/json"})
    try:
        with urlopen(request, timeout=30) as response:  # noqa: S310 - fixed HTTPS endpoint
            body = json.loads(response.read().decode("utf-8"))
        output = body.get("output_text") or ""
        parsed = json.loads(output)
        return parsed if isinstance(parsed, dict) else None
    except Exception:
        return None
