from datetime import datetime, timezone
from uuid import NAMESPACE_URL, UUID, uuid5

from impurity_leads.contacts.models import RankedContact
from impurity_leads.models import Opportunity, Signal
from impurity_leads.normalize import normalize_company_name, normalize_molecule_name
from impurity_leads.contacts.normalize import normalize_person_name, person_name_compatibility


def _stable_uuid(kind: str, value: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"impurity-leads:{kind}:{value}")


class SupabaseLeadStore:
    def __init__(self, client):
        self.client = client
        self._contact_aliases: dict[tuple[str, str], str] = {}

    def _company_id(self, company_name: str) -> str:
        normalized = normalize_company_name(company_name)
        company_id = str(_stable_uuid("company", normalized))
        self.client.table("companies").upsert(
            {
                "id": company_id,
                "normalized_name": normalized,
                "legal_name": company_name,
                "last_seen_at": datetime.now(timezone.utc).isoformat(),
            },
            on_conflict="id",
        ).execute()
        return company_id

    def _molecule_id(self, molecule_name: str) -> str:
        normalized = normalize_molecule_name(molecule_name)
        molecule_id = str(_stable_uuid("molecule", normalized))
        self.client.table("molecules").upsert(
            {
                "id": molecule_id,
                "canonical_name": molecule_name,
                "last_seen_at": datetime.now(timezone.utc).isoformat(),
            },
            on_conflict="id",
        ).execute()
        return molecule_id

    def save_signal(self, signal: Signal) -> None:
        company_id = self._company_id(signal.company_name)
        molecule_id = self._molecule_id(signal.molecule_name) if signal.molecule_name else None
        signal_id = str(_stable_uuid("signal", signal.fingerprint))
        row = {
            "id": signal_id,
            "company_id": company_id,
            "molecule_id": molecule_id,
            "source_type": signal.source_type,
            "signal_type": signal.signal_type,
            "source_url": signal.source_url,
            "source_record_id": signal.source_record_id,
            "evidence_text": signal.evidence_text,
            "event_date": signal.event_date.isoformat() if signal.event_date else None,
            "discovered_at": signal.discovered_at.isoformat(),
            "freshness_days": signal.freshness_days,
            "base_weight": signal.base_weight,
            "confidence": signal.confidence,
            "fingerprint": signal.fingerprint,
            "metadata_json": signal.metadata_json,
        }
        self.client.table("signals").upsert(row, on_conflict="fingerprint").execute()

    def save_opportunity(self, opportunity: Opportunity) -> None:
        company_id = self._company_id(opportunity.company_name)
        molecule_id = self._molecule_id(opportunity.molecule_name)
        opportunity_key = f"{company_id}:{molecule_id}"
        opportunity_id = str(_stable_uuid("opportunity", opportunity_key))
        now = datetime.now(timezone.utc).isoformat()
        row = {
            "id": opportunity_id,
            "company_id": company_id,
            "molecule_id": molecule_id,
            "score": opportunity.score,
            "priority": opportunity.priority,
            "likely_need_type": opportunity.likely_need_type,
            "rationale": opportunity.rationale,
            "decision_maker_role": opportunity.decision_maker_role,
            "last_qualified_at": now,
            "last_signal_at": opportunity.last_signal_at.isoformat() if opportunity.last_signal_at else None,
        }
        self.client.table("opportunities").upsert(
            row,
            on_conflict="company_id,molecule_id",
        ).execute()
        for fingerprint in opportunity.signal_fingerprints:
            signal_id = str(_stable_uuid("signal", fingerprint))
            self.client.table("opportunity_signals").upsert(
                {
                    "opportunity_id": opportunity_id,
                    "signal_id": signal_id,
                    "contribution_score": 0,
                },
                on_conflict="opportunity_id,signal_id",
            ).execute()

    def save_candidate(self, candidate: dict) -> None:
        """Retain a resolved pair even before it reaches the sales threshold."""
        company_id = self._company_id(str(candidate["company_name"]))
        molecule_id = self._molecule_id(str(candidate["molecule_name"]))
        self.client.table("company_molecules").upsert({
            "id": str(_stable_uuid("company-molecule", f"{company_id}:{molecule_id}")),
            "company_id": company_id,
            "molecule_id": molecule_id,
            "candidate_score": candidate.get("score"),
            "candidate_status": "QUALIFIED" if candidate.get("priority") else "UNQUALIFIED",
            "candidate_rationale": candidate.get("rationale") or "",
            "candidate_signal_fingerprints": candidate.get("signal_fingerprints") or [],
            "candidate_last_signal_at": candidate.get("last_signal_at").isoformat() if hasattr(candidate.get("last_signal_at"), "isoformat") else candidate.get("last_signal_at"),
            "candidate_last_evaluated_at": datetime.now(timezone.utc).isoformat(),
        }, on_conflict="company_id,molecule_id").execute()

    def _contact_id(self, company_id: str, normalized_name: str) -> str:
        return str(_stable_uuid("contact", f"{company_id}:{normalized_name}"))

    def _find_existing_contact(self, company_id: str, contact) -> tuple[str, str] | None:
        """Find a canonical person before creating a new company contact.

        Exact normalized names are safe. Abbreviated names are reused only
        when the context is strong (matching profile URL/email or a
        distinctive name plus compatible role); common names never merge on
        name alone.
        """
        normalized = normalize_person_name(contact.display_name)
        cache_key = (company_id, normalized)
        if cache_key in self._contact_aliases:
            return self._contact_aliases[cache_key], normalized
        table = self.client.table("contacts")
        if not hasattr(table, "select"):
            return None
        try:
            query = table.select("id,normalized_name,display_name,title,department,profile_url,primary_email,merged_into_contact_id").eq("company_id", company_id)
            if hasattr(query, "is_"):
                query = query.is_("merged_into_contact_id", "null")
            rows = query.execute().data or []
        except Exception:
            return None
        best: tuple[float, dict] | None = None
        for row in rows:
            score = person_name_compatibility(str(row.get("display_name") or row.get("normalized_name") or ""), contact.display_name)
            if score == 0:
                continue
            exact_route = bool(contact.profile_url and row.get("profile_url") and contact.profile_url.rstrip("/") == str(row["profile_url"]).rstrip("/"))
            exact_email = bool(contact.primary_email and row.get("primary_email") and contact.primary_email.casefold() == str(row["primary_email"]).casefold())
            role_terms = set(str(contact.title or contact.department or "").casefold().split()) & set(str(row.get("title") or row.get("department") or "").casefold().split())
            strong_context = exact_route or exact_email or (score >= 0.9 and len(role_terms) >= 1) or (score >= 0.8 and len(normalized.split()[0]) >= 8 and len(role_terms) >= 1)
            if strong_context and (best is None or score > best[0]):
                best = (score, row)
        if best:
            row = best[1]
            self._contact_aliases[cache_key] = str(row["id"])
            return str(row["id"]), normalize_person_name(str(row.get("display_name") or row.get("normalized_name") or normalized))
        return None

    def _resolved_contact_id(self, company_id: str, contact) -> tuple[str, str]:
        normalized = normalize_person_name(contact.display_name)
        existing = self._find_existing_contact(company_id, contact)
        if existing:
            return existing
        return self._contact_id(company_id, normalized), normalized

    def _opportunity_id(self, opportunity: Opportunity) -> str:
        company_id = str(_stable_uuid("company", normalize_company_name(opportunity.company_name)))
        molecule_id = str(_stable_uuid("molecule", normalize_molecule_name(opportunity.molecule_name)))
        return str(_stable_uuid("opportunity", f"{company_id}:{molecule_id}"))

    def save_contact(self, company_name: str, ranked_contact: RankedContact) -> None:
        company_id = self._company_id(company_name)
        contact = ranked_contact.contact
        contact_id, canonical_name = self._resolved_contact_id(company_id, contact)
        row = {
            "id": contact_id,
            "company_id": company_id,
            "normalized_name": canonical_name,
            "display_name": contact.display_name,
            "title": contact.title,
            "department": contact.department,
            "profile_url": contact.profile_url,
            "primary_email": contact.primary_email,
            "email_status": contact.email_status,
            "primary_phone": contact.primary_phone,
            "phone_status": contact.phone_status,
            "role_fit_score": contact.role_fit_score,
            "contact_confidence": contact.contact_confidence,
            "first_seen_at": contact.first_seen_at.isoformat() if contact.first_seen_at else None,
            "last_seen_at": contact.last_seen_at.isoformat() if contact.last_seen_at else None,
            "last_verified_at": contact.last_verified_at.isoformat() if contact.last_verified_at else None,
        }
        # Keep the crawler RPC whitelist/idempotency contract unchanged.
        self.client.table("contacts").upsert(row, on_conflict="company_id,normalized_name").execute()
        self._contact_aliases[(company_id, normalize_person_name(contact.display_name))] = contact_id
        for evidence in contact.evidence:
            evidence_row = {
                "id": str(_stable_uuid("contact-evidence", evidence.fingerprint)),
                "contact_id": contact_id,
                "evidence_type": evidence.evidence_type,
                "observed_value": evidence.observed_value,
                "source_type": evidence.source_type,
                "source_url": evidence.source_url,
                "evidence_text": evidence.evidence_text[:800],
                "observed_at": evidence.observed_at.isoformat(),
                "fingerprint": evidence.fingerprint,
                "metadata_json": evidence.metadata_json,
            }
            self.client.table("contact_evidence").upsert(evidence_row, on_conflict="fingerprint").execute()

    def link_opportunity_contact(self, opportunity: Opportunity, ranked_contact: RankedContact) -> None:
        company_id = self._company_id(opportunity.company_name)
        contact_id, _ = self._resolved_contact_id(company_id, ranked_contact.contact)
        opportunity_id = self._opportunity_id(opportunity)
        self.client.table("opportunity_contacts").upsert(
            {
                "opportunity_id": opportunity_id,
                "contact_id": contact_id,
                "role_fit_score": ranked_contact.contact.role_fit_score,
                "rank": ranked_contact.rank,
                "rationale": ranked_contact.rationale,
            },
            on_conflict="opportunity_id,contact_id",
        ).execute()


def create_supabase_store(url: str, secret_key: str) -> SupabaseLeadStore:
    from supabase import create_client

    return SupabaseLeadStore(create_client(url, secret_key))
