from datetime import datetime, timezone

from impurity_leads.adapters.base import SourceAdapter
from impurity_leads.models import SourceRecord


class FDAAdapter(SourceAdapter):
    name = "openfda"

    def parse(self, payload: dict) -> list[SourceRecord]:
        result = payload
        sponsor = result.get("sponsor_name")
        openfda = result.get("openfda", {})
        if not sponsor:
            manufacturers = openfda.get("manufacturer_name") or []
            sponsor = manufacturers[0] if manufacturers else None

        ingredients: list[str] = []
        for product in result.get("products", []):
            for ingredient in product.get("active_ingredients", []):
                name = ingredient.get("name")
                if name and name not in ingredients:
                    ingredients.append(name)
        for name in openfda.get("substance_name") or []:
            if name and name not in ingredients:
                ingredients.append(name)

        records: list[SourceRecord] = []
        application_number = result.get("application_number")
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
