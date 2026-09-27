"""Build an idempotent SQL batch for validated public current-contact records."""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5


def esc(value: object) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, float)):
        return str(value)
    return "'" + str(value).replace("\\", "\\\\").replace("'", "''") + "'"


def json_sql(value: object) -> str:
    return f"{esc(json.dumps(value, ensure_ascii=False, separators=(',', ':')))}::jsonb"


def norm(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", value.casefold())).strip()


def person_norm(value: str) -> str:
    return " ".join(w for w in norm(value).split() if w not in {"dr", "prof", "mr", "mrs", "ms", "miss", "sir"})


def stable(kind: str, value: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"impurity-leads:{kind}:{value}"))


opportunities = json.loads(Path("/tmp/production_opportunities.json").read_text())
company_rows: dict[str, list[dict]] = {}
opps_by_company: dict[str, list[dict]] = {}
for row in opportunities:
    company_rows.setdefault(norm(row["company_name"]), []).append(row)
    opps_by_company.setdefault(row["company_id"], []).append(row)

aliases = {
    "zydus lifesciences": "zydus lifesciences limited",
    "novartis": "novartis pharmaceuticals",
    "jubilant generics limited": "jubilant generics",
}

people: dict[tuple[str, str], dict] = {}
for path in (Path("outputs/contact_discovery_agent.json"), Path("outputs/contact_discovery_production_remaining.json")):
    if not path.exists():
        continue
    payload = json.loads(path.read_text())
    for account in payload.get("accounts", []):
        key = aliases.get(norm(account.get("company") or ""), norm(account.get("company") or ""))
        if key not in company_rows:
            continue
        for person in account.get("contacts", []):
            name = person.get("name")
            if name:
                people[(key, person_norm(name))] = {**person, "company_key": key}

now = datetime.now(timezone.utc).isoformat()
statements: list[str] = ["begin;"]
for person in people.values():
  for row in company_rows[person["company_key"]]:
    company_id = row["company_id"]
    normalized = person_norm(person["name"])
    contact_id = stable("contact", f"{company_id}:{normalized}")
    confidence = {"HIGH": 0.9, "MEDIUM": 0.7, "LOW": 0.45}.get(str(person.get("status_confidence", "MEDIUM")).upper(), 0.6)
    current_status = person.get("current_status") or ("PROFESSIONAL_PROFILE" if person.get("profile_url") else "UNKNOWN")
    metadata = {
        "current_status": current_status,
        "status_confidence": person.get("status_confidence"),
        "observed_context": person.get("observed_context"),
        "inferred_jtbd": person.get("inferred_jtbd") or [],
        "jtbd_confidence": person.get("jtbd_confidence"),
        "recommended_channel": person.get("recommended_channel"),
        "contact_path": person.get("contact_path"),
        "professional_themes": [],
    }
    values = [
        esc(contact_id), esc(company_id), esc(normalized), esc(person["name"]), esc(person.get("title")),
        esc(person.get("function")), esc(person.get("profile_url")), esc(person.get("email")),
        esc(person.get("email_status") or "ROLE_ONLY"), esc(person.get("phone")), esc(person.get("phone_status") or "ROLE_ONLY"),
        str(int(person.get("role_fit") or person.get("role_fit_score") or 0)), str(confidence), esc(now), esc(now), esc(now),
    ]
    statements.append(
        "insert into public.contacts (id,company_id,normalized_name,display_name,title,department,profile_url,primary_email,email_status,primary_phone,phone_status,role_fit_score,contact_confidence,first_seen_at,last_seen_at,last_verified_at) values ("
        + ",".join(values)
        + ") on conflict (company_id,normalized_name) do update set title=excluded.title, department=excluded.department, profile_url=coalesce(excluded.profile_url,public.contacts.profile_url), role_fit_score=greatest(public.contacts.role_fit_score,excluded.role_fit_score), contact_confidence=greatest(public.contacts.contact_confidence,excluded.contact_confidence), last_seen_at=excluded.last_seen_at, last_verified_at=excluded.last_verified_at;"
    )
    urls = person.get("evidence_urls") or ([] if not person.get("profile_url") else [person["profile_url"]])
    for index, url in enumerate(dict.fromkeys(urls)):
        evidence_type = "title" if index == 0 else "affiliation"
        observed = person.get("title") if evidence_type == "title" else row["company_name"]
        fingerprint = stable("contact-evidence", f"{contact_id}:{evidence_type}:{url}")
        text = (person.get("observed_context") or f"Public professional source links {person['name']} with {row['company_name']}.")[:800]
        statements.append(
            "insert into public.contact_evidence (id,contact_id,evidence_type,observed_value,source_type,source_url,evidence_text,observed_at,fingerprint,metadata_json) values ("
            + ",".join([esc(stable("contact-evidence-row", fingerprint)), esc(contact_id), esc(evidence_type), esc(observed or person["name"]), esc("professional_profile"), esc(url), esc(text), esc(now), esc(fingerprint), json_sql(metadata)])
            + ") on conflict (fingerprint) do update set evidence_text=excluded.evidence_text, observed_at=excluded.observed_at, metadata_json=excluded.metadata_json;"
        )
    for rank, opp in enumerate(sorted(opps_by_company.get(company_id, []), key=lambda x: (-x["score"], x["molecule_name"]))[:3], start=1):
        rationale = f"Current {person.get('function') or 'technical/quality'} role is account-relevant; molecule-specific requirement remains to be confirmed."
        statements.append(
            "insert into public.opportunity_contacts (opportunity_id,contact_id,role_fit_score,rank,rationale) values ("
            + ",".join([esc(opp["id"]), esc(contact_id), str(int(person.get("role_fit") or person.get("role_fit_score") or 0)), str(rank), esc(rationale)])
            + ") on conflict (opportunity_id,contact_id) do update set role_fit_score=excluded.role_fit_score, rank=excluded.rank, rationale=excluded.rationale;"
        )

statements.append("commit;")
Path("/tmp/contact_write.sql").write_text("\n".join(statements) + "\n")
print(json.dumps({"people": len(people), "statements": len(statements)}))
