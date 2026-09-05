from datetime import datetime, timezone

from dateutil.parser import isoparse

from impurity_leads.adapters.base import SourceAdapter
from impurity_leads.models import SourceRecord


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
        sponsor = sponsors.get("leadSponsor", {}).get("name")
        phases = design.get("phases") or []
        phase = phases[0] if phases else None
        countries = sorted({loc.get("country") for loc in locations.get("locations", []) if loc.get("country")})
        date_text = (
            status.get("lastUpdatePostDateStruct", {}).get("date")
            or status.get("studyFirstPostDateStruct", {}).get("date")
        )
        published_at = isoparse(date_text) if date_text else None
        if published_at and published_at.tzinfo is None:
            published_at = published_at.replace(tzinfo=timezone.utc)

        records: list[SourceRecord] = []
        for intervention in arms.get("interventions", []):
            if intervention.get("type") != "DRUG":
                continue
            molecule = intervention.get("name")
            if not molecule:
                continue
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
