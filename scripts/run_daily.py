from impurity_leads.cli import main
from impurity_leads.config import load_settings
from impurity_leads.contact_research import run_pending_contact_research


if __name__ == "__main__":
    exit_code = main(["run-daily"])
    # Contact research is a bounded post-crawl stage. It uses the same
    # backend-only Supabase credentials and never exposes them to the UI.
    try:
        run_pending_contact_research(load_settings(), limit=10)
    except Exception:
        # A research outage must not invalidate the completed lead crawl.
        pass
    raise SystemExit(exit_code)
