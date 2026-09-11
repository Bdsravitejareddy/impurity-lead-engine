import json

from impurity_leads.cli import main
from impurity_leads.config import load_settings
from impurity_leads.contact_research import run_pending_contact_research


if __name__ == "__main__":
    exit_code = main(["run-daily"])
    # Contact research is a bounded post-crawl stage. It uses the same
    # backend-only Supabase credentials and never exposes them to the UI.
    try:
        result = run_pending_contact_research(load_settings(), limit=10)
        print(json.dumps({"event": "contact_research", **result}, sort_keys=True))
    except Exception as exc:
        # A research outage must not invalidate the completed lead crawl, but
        # it must remain visible in the Actions log for diagnosis/retry.
        print(json.dumps({"event": "contact_research_failed", "error": type(exc).__name__}, sort_keys=True))
    raise SystemExit(exit_code)
