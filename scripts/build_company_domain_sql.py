import json
from pathlib import Path
from urllib.parse import urlparse

def esc(v):
    return "'" + str(v).replace("'", "''") + "'"

seen = {}
for path in ('outputs/contact_discovery_agent.json', 'outputs/contact_discovery_production_remaining.json'):
    payload = json.loads(Path(path).read_text())
    for account in payload.get('accounts', []):
        route = account.get('company_route') or {}
        url = route.get('url')
        context = ' '.join(str(p.get('observed_context') or '') for p in account.get('contacts', []))
        if url and url.startswith('http') and not any(word in context.casefold() for word in ('legacy entity', 'acquired', 'current operating identity')):
            host = urlparse(url).netloc.casefold().removeprefix('www.')
            if host:
                seen[account['company']] = host
statements = ['begin;']
for company, domain in sorted(seen.items()):
    statements.append(f"update public.companies set domain={esc(domain)} where legal_name={esc(company)} and (domain is null or domain='');")
statements.append('commit;')
Path('/tmp/company_domain_write.sql').write_text('\n'.join(statements)+'\n')
print({'companies':len(seen)})
