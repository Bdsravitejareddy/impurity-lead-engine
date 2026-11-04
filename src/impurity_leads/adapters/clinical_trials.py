from datetime import datetime, timezone

from dateutil.parser import isoparse

from impurity_leads.adapters.base import SourceAdapter
from impurity_leads.models import SourceRecord
from impurity_leads.normalize import clean_intervention_names


# Trials that will not run or whose outcome is unknown carry no sourcing demand.
_INACTIVE_STATUSES = {"WITHDRAWN", "TERMINATED", "SUSPENDED", "UNKNOWN"}
_PHASE_ORDER = {"EARLY_PHASE1": 0, "PHASE1": 1, "PHASE2": 2, "PHASE3": 3, "PHASE4": 4}


def _industry_sponsor(sponsors: dict) -> str | None:
    """Universities, hospitals and research networks are not impurity buyers."""
    lead = sponsors.get("leadSponsor", {})
    if lead.get("class") in (None, "INDUSTRY") and lead.get("name"):
        return lead["name"]
    return next((item.get("name") for item in sponsors.get("collaborators", []) if item.get("class") == "INDUSTRY" and item.get("name")), None)


class ClinicalTrialsAdapter(SourceAdapter):
    name = "clinicaltrials.gov"

    def parse(self, payload: dict) -> list[SourceRecord]:
        protocol = payload.get("protocolSection", payload)
        identification = protocol.get("identificationModule", {})
        status = protocol.get("statusModule", {})
        sponsors = protocol.get("sponsorCollaboratorsModule", {})
        design = protocol.get("designModule", {})
        arms = protocol.get("armsInterventionsModule", {})
        locations = protocol.get("contactsLocationsModule", {})

        nct_id = identification.get("nctId")
        if str(status.get("overallStatus") or "").upper() in _INACTIVE_STATUSES:
            return []
        sponsor = _industry_sponsor(sponsors)
        if not sponsor:
            return []
        phases = design.get("phases") or []
        # ["PHASE2", "PHASE3"] is a phase 2/3 trial; weigh it by its latest phase.
        phase = max(phases, key=lambda value: _PHASE_ORDER.get(value, -1)) if phases else None
        countries = sorted({loc.get("country") for loc in locations.get("locations", []) if loc.get("country")})
        date_text = (
            status.get("lastUpdatePostDateStruct", {}).get("date")
            or status.get("studyFirstPostDateStruct", {}).get("date")
        )
        published_at = isoparse(date_text) if date_text else None
        if published_at and published_at.tzinfo is None:
            published_at = published_at.replace(tzinfo=timezone.utc)

        records: list[SourceRecord] = []
        molecules: list[tuple[str, dict]] = []
        for intervention in arms.get("interventions", []):
            if intervention.get("type") != "DRUG":
                continue
            for molecule in clean_intervention_names(intervention.get("name") or ""):
                if molecule.casefold() not in {name.casefold() for name, _ in molecules}:
                    molecules.append((molecule, intervention))
        for molecule, intervention in molecules:
            signal_text = " ".join(
                part for part in [
                    identification.get("briefTitle", ""),
                    f"Phase {phase}" if phase else "",
                    intervention.get("description", ""),
                ] if part
            )
            records.append(
                SourceRecord(
                    source_name=self.name,
                    source_type="trial",
                    source_record_id=nct_id,
                    source_url=f"https://clinicaltrials.gov/study/{nct_id}" if nct_id else "https://clinicaltrials.gov/",
                    published_at=published_at,
                    fetched_at=datetime.now(timezone.utc),
                    company_name_raw=sponsor,
                    molecule_name_raw=molecule,
                    signal_text=signal_text,
                    country=countries[0] if len(countries) == 1 else None,
                    metadata_json={
                        "phase": phase,
                        "overall_status": status.get("overallStatus"),
                        "countries": countries,
                    },
                )
            )
        return records
