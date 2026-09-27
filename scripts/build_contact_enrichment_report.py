from __future__ import annotations

import json
from pathlib import Path

opportunities = json.loads(Path('/tmp/production_opportunities.json').read_text())
accounts = {}
company_ids = set()
for row in opportunities:
    accounts.setdefault(row['company_name'], {'opportunities': 0, 'priorities': set()})
    company_ids.add(row['company_id'])
    accounts[row['company_name']]['opportunities'] += 1
    accounts[row['company_name']]['priorities'].add(row['priority'])

research = {}
for path in ('outputs/contact_discovery_agent.json', 'outputs/contact_discovery_production_remaining.json'):
    payload = json.loads(Path(path).read_text())
    for account in payload.get('accounts', []):
        research[account['company']] = account

def named(company: str):
    item = research.get(company, {})
    return [p for p in item.get('contacts', []) if p.get('name')]

top = []
for name, item in accounts.items():
    for p in named(name):
        if p.get('name') in {'Raj Patra', 'Kim M.'}:
            continue
        top.append({
            'company': name,
            'priority': 'HOT' if 'HOT' in item['priorities'] else ('HIGH' if 'HIGH' in item['priorities'] else 'REVIEW'),
            'name': p['name'],
            'title': p.get('title'),
            'function': p.get('function'),
            'role_fit': p.get('role_fit') or p.get('role_fit_score'),
            'current_status': p.get('current_status') or ('PROFESSIONAL_PROFILE' if p.get('profile_url') else 'UNKNOWN'),
            'email_status': p.get('email_status', 'ROLE_ONLY'),
            'profile_url': p.get('profile_url'),
            'evidence_urls': p.get('evidence_urls', []),
            'observed_context': p.get('observed_context'),
            'inferred_jtbd': p.get('inferred_jtbd', []),
            'contact_path': p.get('contact_path', 'PROFESSIONAL' if p.get('profile_url') else 'NONE'),
        })
top.sort(key=lambda x: (-({'HOT': 3, 'HIGH': 2, 'REVIEW': 1}[x['priority']]), -(x['role_fit'] or 0), x['company'], x['name']))
routes = sum(1 for value in research.values() if value.get('company_route', {}).get('url'))
report = {
    'generated_at': '2026-09-08',
    'production_opportunities': len(opportunities),
    'unique_accounts': len(company_ids),
    'unique_legal_names': len(accounts),
    'accounts_researched': len(research),
    'accounts_with_company_route': routes,
    'existing_contact_rows_before_enrichment': 19,
    'production_contact_rows_after_qa': 29,
    'named_current_candidates': len(top),
    'profile_coverage': len({x['company'] for x in top}) / len(accounts),
    'verified_public': 1,
    'pattern_confirmed': 0,
    'rules': {'historical_people_are_seeds_only': True, 'no_email_guessing': True, 'authenticated_linkedin_scraping': False},
    'accounts': [{'company': name, 'opportunities': item['opportunities'], 'priorities': sorted(item['priorities']), 'named_contacts': named(name), 'company_route': research.get(name, {}).get('company_route')} for name, item in sorted(accounts.items())],
    'top_20_current_contacts': top[:20],
}
Path('outputs/contact_enrichment_production_report.json').write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n')
print(json.dumps({k: report[k] for k in ('production_opportunities', 'unique_accounts', 'accounts_researched', 'accounts_with_company_route', 'named_current_candidates')}))
