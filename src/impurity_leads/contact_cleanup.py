"""Clean contacts stored before extraction rejected headings and biographies.

Older crawls stored section headings ("Board of Directors", "Key Contacts")
as people, and whole biographies as job titles. This stage applies the same
rules the extractor now uses to rows already in the database:

- a row whose name is not a person is hidden (``hidden_reason``), not deleted,
  so nothing linked to it is lost;
- a title that repeats the name or runs to a biography is cut to the title,
  or cleared when no short title can be found.

It is idempotent and runs on every daily crawl.
"""
from __future__ import annotations

import re
from typing import Any

from impurity_leads.contacts.extract import TITLE_MAX, _clean_title, _plausible_name
from impurity_leads.seed_sources import _paged


def contact_fix(row: dict[str, Any]) -> dict[str, Any] | None:
    """The update a stored contact needs, or None when it is already clean."""
    name = re.sub(r"\s+", " ", str(row.get("display_name") or "")).strip()
    if row.get("hidden_reason"):
        return None
    if not _plausible_name(name):
        return {"hidden_reason": "not_a_person"}
    title = str(row.get("title") or "").strip()
    if not title:
        return None
    needs_cleaning = len(title) > TITLE_MAX or title.casefold().startswith(name.casefold())
    if not needs_cleaning:
        return None
    # A biography's title is usually its first clause: "CEO – Lupin Manufacturing Solutions Abdel is a ...".
    if title.casefold().startswith(name.casefold()):
        title = title[len(name):].strip(" ,–—-:|")
    first_clause = re.split(r"(?<=[a-z\)])\s+(?=[A-Z][a-z]+ (?:is|has|was|joined|leads|heads|brings)\b)|[.;]\s", title, maxsplit=1)[0]
    return {"title": _clean_title(first_clause, name)}


def run_contact_cleanup(client) -> dict[str, Any]:
    rows = _paged(lambda: client.table("contacts").select("id,display_name,title,hidden_reason")
                  .is_("merged_into_contact_id", "null").order("id"))
    hidden, retitled = 0, 0
    for row in rows:
        fix = contact_fix(row)
        if not fix:
            continue
        client.table("contacts").update(fix).eq("id", row["id"]).execute()
        hidden += "hidden_reason" in fix
        retitled += "title" in fix
    return {"status": "COMPLETED", "checked": len(rows), "hidden_not_a_person": hidden, "titles_cleaned": retitled}
