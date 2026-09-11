from impurity_leads.person_discovery import affiliation_matches_company, extract_authors, rank_candidate


def test_publication_authors_and_affiliations_are_preserved():
    item = {"title": "Impurity characterization", "pmid": "1", "firstPublicationDate": "2024-01-01", "authorList": {"author": [{"fullName": "Vijayasarathi R", "firstName": "Vijayasarathi", "lastName": "R", "affiliation": "Cipla Limited, Analytical Development", "correspondingAuthor": True}]}}
    candidates = extract_authors(item, technical_text=item["title"])
    assert candidates[0].name == "Vijayasarathi R"
    assert candidates[0].corresponding is True
    assert affiliation_matches_company(candidates[0].affiliation, "Cipla")


def test_common_name_without_target_affiliation_is_not_promoted():
    item = {"authorString": "Jitendra Singh; Another Person", "firstPublicationDate": "2015"}
    candidates = extract_authors(item)
    assert len(candidates) == 2
    assert not affiliation_matches_company(None, "Cipla")


def test_candidate_ranking_rewards_direct_technical_context_and_corresponding_author():
    candidate = extract_authors({"authorList": {"author": [{"fullName": "A Person", "correspondingAuthor": True}]}}, technical_text="impurity degradation analytical method")[0]
    assert rank_candidate(candidate, company_match=True) >= 70
