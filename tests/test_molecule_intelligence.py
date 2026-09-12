from impurity_leads.molecule_intelligence import build_intelligence_sections, missing_molecule_dimensions, normalize_claim_type
from impurity_leads.agent_research import active_agent_dedupe_key, validate_agent_submission


def test_molecule_claim_types_are_normalized_and_sections_keep_claim_ids():
    assert normalize_claim_type('clinical safety') == 'CLINICAL_SAFETY'
    sections = build_intelligence_sections([
        {'id': 'claim-1', 'claim_type': 'CLINICAL_SAFETY', 'claim_text': 'Label reports nausea.', 'provenance': 'OBSERVED', 'confidence': 0.9, 'source_id': 'source-1'},
        {'id': 'claim-2', 'claim_type': 'TOXICOLOGY', 'claim_text': 'Study reports genotoxicity testing.', 'provenance': 'OBSERVED', 'confidence': 0.8, 'source_id': 'source-2'},
    ])
    assert sections['CLINICAL_SAFETY']['supporting_claim_ids'] == ['claim-1']
    assert sections['CLINICAL_SAFETY']['evidence_status'] == 'SUPPORTED'
    assert sections['TOX_HAZARD']['supporting_claim_ids'] == ['claim-2']


def test_molecule_work_result_requires_source_for_observed_claims():
    result = validate_agent_submission({
        'job_id': 'job-1', 'job_kind': 'MOLECULE_INTELLIGENCE',
        'molecule': {'canonical_name': 'Cobimetinib', 'claims': [{'claim': 'Used in cancer treatment', 'claim_type': 'CLINICAL_USE', 'proposed_provenance': 'OBSERVED', 'source_urls': []}]},
        'sources': [],
    }, job_id='job-1', job_kind='MOLECULE_INTELLIGENCE')
    assert result['valid'] is False
    assert result['data']['molecule']['claims'][0]['proposed_provenance'] == 'INFERRED'


def test_molecule_invalid_claim_url_cannot_support_observed_claim():
    result = validate_agent_submission({
        'job_id': 'job-1', 'job_kind': 'MOLECULE_INTELLIGENCE',
        'molecule': {'canonical_name': 'Cobimetinib', 'claims': [{'claim': 'Label fact', 'claim_type': 'CLINICAL_USE', 'proposed_provenance': 'OBSERVED', 'source_urls': ['not-a-url']}]},
        'sources': [],
    }, job_id='job-1', job_kind='MOLECULE_INTELLIGENCE')
    assert result['data']['molecule']['claims'][0]['proposed_provenance'] == 'INFERRED'


def test_molecule_dedupe_key_is_separate_from_contact_jobs():
    assert active_agent_dedupe_key(None, ['CLINICAL_USE'], job_kind='MOLECULE_INTELLIGENCE', molecule_id='mol-1') == 'molecule:mol-1:CLINICAL_USE'
    assert active_agent_dedupe_key('opp-1', ['CURRENT_ROLE']) == 'opp-1:CURRENT_ROLE'


def test_missing_molecule_dimensions_only_returns_unsupported_sections():
    assert missing_molecule_dimensions([{'section_type': 'WHAT_IT_IS', 'evidence_status': 'SUPPORTED'}]) == ['CLINICAL_USE', 'CLINICAL_SAFETY', 'TOXICOLOGY', 'IMPURITY_RELEVANCE', 'ANALYTICAL_RELEVANCE']
