"""Request parameters for the structured sources, shared by the CLI and the daily runner.

Both sources used to be read as one unsorted page: ClinicalTrials.gov returned
100 studies by relevance and openFDA the first 99 applications of its index,
which surfaced decades-old ANDAs. They now ask for recent, active,
industry-sponsored records, newest first.
"""
from datetime import date, timedelta

CLINICAL_TRIALS_URL = "https://clinicaltrials.gov/api/v2/studies"
FDA_URL = "https://api.fda.gov/drug/drugsfda.json"
# Pages read per source per run; each page is one request.
MAX_PAGES = 3
FDA_PAGE_SIZE = 99
FDA_LOOKBACK_DAYS = 365


def clinical_trials_params(page_token: str | None = None) -> dict:
    params = {
        "query.term": "AREA[Phase]PHASE3 AND AREA[InterventionType]DRUG AND AREA[LeadSponsorClass]INDUSTRY",
        "filter.overallStatus": "RECRUITING,ACTIVE_NOT_RECRUITING,NOT_YET_RECRUITING,ENROLLING_BY_INVITATION,COMPLETED",
        "sort": "LastUpdatePostDate:desc",
        "pageSize": 100,
        "format": "json",
    }
    if page_token:
        params["pageToken"] = page_token
    return params


def fda_params(page: int = 0, today: date | None = None) -> dict:
    today = today or date.today()
    start = today - timedelta(days=FDA_LOOKBACK_DAYS)
    return {
        "search": f"submissions.submission_status_date:[{start:%Y%m%d} TO {today:%Y%m%d}]",
        "sort": "submissions.submission_status_date:desc",
        "limit": FDA_PAGE_SIZE,
        "skip": page * FDA_PAGE_SIZE,
    }
