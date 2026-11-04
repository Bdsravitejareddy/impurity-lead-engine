#!/usr/bin/env python3
"""Record live Europe PMC / ORCID (and PatentsView, with a key) responses.

Tests replay these files; they never call the network. Payloads are trimmed to
the fields the discovery stage reads so fixtures stay small and reviewable.

    python scripts/record_molecule_discovery_fixtures.py "Merck & Co., Inc.|sitagliptin" ...
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from impurity_leads.molecule_discovery import OpportunityTarget, PoliteFetcher, discover_for_opportunity, http_get_json

OUT = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "molecule_discovery" / "responses.json"
_EPMC_KEYS = ("id", "source", "pmid", "doi", "title", "abstractText", "authorString", "authorList", "firstPublicationDate", "pubYear", "journalInfo")


def _trim(url: str, payload: dict) -> dict:
    if "europepmc" in url:
        results = (payload.get("resultList") or {}).get("result") or []
        trimmed = []
        for item in results:
            row = {key: item[key] for key in _EPMC_KEYS if key in item}
            if "journalInfo" in row:
                row["journalInfo"] = {"journal": {"title": ((row["journalInfo"].get("journal") or {}).get("title"))}}
            trimmed.append(row)
        return {"hitCount": payload.get("hitCount"), "resultList": {"result": trimmed}}
    if "orcid.org" in url:
        groups = []
        for group in payload.get("affiliation-group") or []:
            summaries = [{"employment-summary": {key: (summary.get("employment-summary") or {}).get(key) for key in ("department-name", "role-title", "start-date", "end-date", "organization")}} for summary in group.get("summaries") or []]
            groups.append({"summaries": summaries})
        return {"last-modified-date": payload.get("last-modified-date"), "affiliation-group": groups}
    return payload


def main(argv: list[str]) -> int:
    recorded: dict[str, dict] = json.loads(OUT.read_text()) if OUT.exists() else {}

    def recording_fetch(url: str, headers: dict[str, str]) -> dict:
        payload = _trim(url, http_get_json(url, headers))
        recorded[url] = payload
        return payload

    fetch = PoliteFetcher(recording_fetch, user_agent=os.environ.get("CRAWLER_USER_AGENT", "SVAK-Impurity-Lead-Research/0.1"), delay_seconds=1.0)
    for index, spec in enumerate(argv, start=1):
        company, molecule = spec.split("|", 1)
        target = OpportunityTarget(opportunity_id=f"opp-{index}", company_id=f"company-{index}", company_name=company, molecule_name=molecule)
        result = discover_for_opportunity(target, fetch, patentsview_api_key=os.environ.get("PATENTSVIEW_API_KEY"))
        print(json.dumps({"company": company, "molecule": molecule, "people": len(result["people"]), "errors": result["errors"]}))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(recorded, indent=1, sort_keys=True, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
