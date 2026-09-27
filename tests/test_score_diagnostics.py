from datetime import datetime, timezone
from impurity_leads.models import Signal
from impurity_leads.score_diagnostics import explain_score

def _s(kind, weight, source, date):
    return Signal(company_name='L', molecule_name='M', source_type=source, signal_type=kind,
      source_url='https://x/'+kind, evidence_text='x', event_date=date,
      discovered_at=datetime(2026,9,6,tzinfo=timezone.utc), base_weight=weight,
      confidence=1.0, fingerprint=kind)

def test_explain_score_reports_freshness_and_diversity():
    now=datetime(2026,9,6,tzinfo=timezone.utc)
    result=explain_score([_s('regulatory_application',22,'fda',datetime(2024,12,13,tzinfo=timezone.utc)),
                          _s('degradation_product',35,'regulatory',datetime(2024,5,1,tzinfo=timezone.utc)),
                          _s('stability',18,'regulatory',datetime(2024,5,1,tzinfo=timezone.utc))], now=now)
    assert result['raw_total'] == 75
    assert result['diversity_bonus'] == 4
    assert result['urgency_bonus'] == 3
    assert result['clamped_total'] == 82
    assert result['priority'] == 'HOT'
    assert [x['effective_contribution'] for x in result['signals']] == [22,35,18]
