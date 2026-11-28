from datetime import date

from impurity_leads.adapters.publications import PublicationAdapter, company_from_affiliation, molecule_from_paper
from impurity_leads.adapters.queries import publication_params
from impurity_leads.pipeline import process_records_with_candidates
from impurity_leads.storage.memory import MemoryLeadStore


def paper(**overrides):
    item = {
        "pmid": "41000001", "title": "Trace analysis of genotoxic impurity 3-amino-N-nitrosopiperidine in alogliptin benzoate",
        "abstractText": "A sensitive LC-MS/MS method was validated for the nitrosamine impurity (NDSRI) in alogliptin drug substance.",
        "firstPublicationDate": "2026-10-01", "journalTitle": "J Pharm Biomed Anal",
        "chemicalList": {"chemical": [{"name": "Nitrosamines"}, {"name": "Mutagens"}, {"name": "alogliptin"}]},
        "authorList": {"author": [
            {"authorAffiliationDetailsList": {"authorAffiliation": [{"affiliation": "Analytical R&D, Indoco Remedies Limited, Mumbai, India."}]}},
            {"authorAffiliationDetailsList": {"authorAffiliation": [{"affiliation": "Department of Chemistry, University of Mumbai, India."}]}},
        ]},
    }
    item.update(overrides)
    return item


def test_company_is_read_from_the_affiliation_and_academics_are_skipped():
    assert company_from_affiliation("Analytical R&D, Indoco Remedies Limited, Mumbai, India.") == "Indoco Remedies Limited"
    assert company_from_affiliation("Drug Product Technologies, Process Development, Amgen, Inc., Thousand Oaks") == "Amgen Inc"
    assert company_from_affiliation("Department of Chemistry, GITAM Deemed to be University, Visakhapatnam") is None
    assert company_from_affiliation("Klinikum Bayreuth GmbH, Bayreuth, Germany") is None


def test_molecule_is_a_specific_compound_not_a_class():
    assert molecule_from_paper(paper()) == "alogliptin"
    assert molecule_from_paper(paper(chemicalList={}, title="Forced degradation study of etrasimod")) == "etrasimod"


def test_company_paper_becomes_a_hot_lead_and_university_only_papers_do_not():
    [record] = PublicationAdapter().parse(paper())
    assert record.company_name_raw == "Indoco Remedies Limited" and record.source_type == "publication"
    assert record.published_at.year == 2026
    opportunities, _ = process_records_with_candidates([record], MemoryLeadStore())
    assert opportunities[0].priority == "HOT"
    academic = {"author": [{"authorAffiliationDetailsList": {"authorAffiliation": [{"affiliation": "School of Chemistry, South China Normal University"}]}}]}
    assert PublicationAdapter().parse(paper(authorList=academic)) == []


def test_non_drugs_vendors_and_unconfirmed_molecules_are_skipped():
    assert PublicationAdapter().parse(paper(chemicalList={"chemical": [{"name": "Cellulose"}]})) == []
    vendor = {"author": [{"authorAffiliationDetailsList": {"authorAffiliation": [{"affiliation": "Sigma Aldrich Production GmbH, Buchs"}]}}]}
    assert PublicationAdapter().parse(paper(authorList=vendor)) == []
    assert PublicationAdapter(is_drug=lambda name: False).parse(paper()) == []
    assert PublicationAdapter(is_drug=lambda name: name == "alogliptin").parse(paper())


def test_query_covers_two_years_newest_first():
    params = publication_params(today=date(2026, 11, 28))
    assert "FIRST_PDATE:[2024-11-28 TO 2026-11-28]" in params["query"]
    assert params["sort"] == "FIRST_PDATE_D desc" and params["cursorMark"] == "*"
