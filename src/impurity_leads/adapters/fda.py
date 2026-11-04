from datetime import datetime, timezone

from impurity_leads.adapters.base import SourceAdapter
from impurity_leads.models import SourceRecord


class FDAAdapter(SourceAdapter):
    name = "openfda"

    def parse(self, payload: dict) -> list[SourceRecord]:
        result = payload
        application_number = result.get("application_number")
        # Biologics (BLA) need different analytical work than small-molecule impurities.
        if str(application_number or "").upper().startswith("BLA"):
            return []
        sponsor = result.get("sponsor_name")
        openfda = result.get("openfda", {})
        if not sponsor:
            manufacturers = openfda.get("manufacturer_name") or []
            sponsor = manufacturers[0] if manufacturers else None

        products = result.get("products", [])
        marketed = [product for product in products if str(product.get("marketing_status") or "").casefold() != "discontinued"]
        if products and not marketed:
            return []

        # substance_name is the harmonised ingredient name; active_ingredients
        # repeats it per product with salt/form suffixes, so use it only as a fallback.
        ingredients: list[str] = []
        candidates = openfda.get("substance_name") or [ingredient.get("name") for product in marketed for ingredient in product.get("active_ingredients", [])]
        for name in candidates:
            if name and name.casefold() not in {existing.casefold() for existing in ingredients}:
                ingredients.append(name)

        status_dates = [str(item.get("submission_status_date") or "") for item in result.get("submissions", [])]
        latest = max((value for value in status_dates if len(value) == 8 and value.isdigit()), default=None)
        published_at = datetime.strptime(latest, "%Y%m%d").replace(tzinfo=timezone.utc) if latest else None

        records: list[SourceRecord] = []
        for ingredient in ingredients:
            records.append(
                SourceRecord(
                    source_name=self.name,
                    source_type="regulatory",
                    source_record_id=application_number,
                    source_url=(
                        f"https://api.fda.gov/drug/drugsfda.json?search=application_number:{application_number}"
                        if application_number
                        else "https://api.fda.gov/drug/drugsfda.json"
                    ),
                    published_at=published_at,
                    fetched_at=datetime.now(timezone.utc),
                    company_name_raw=sponsor,
                    molecule_name_raw=ingredient,
                    active_ingredient_raw=ingredient,
                    signal_text=" ".join(
                        part for part in [application_number or "", ingredient, "FDA application activity"] if part
                    ),
                    metadata_json={"application_number": application_number},
                )
            )
        return records
