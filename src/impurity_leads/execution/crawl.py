"""Small durable adapters around the existing extraction and scoring code."""
from contextlib import nullcontext
from datetime import datetime, timezone
from urllib.parse import urlparse

import httpx
from impurity_leads.adapters.clinical_trials import ClinicalTrialsAdapter
from impurity_leads.adapters.fda import FDAAdapter
from impurity_leads.adapters.queries import CLINICAL_TRIALS_URL, FDA_PAGE_SIZE, FDA_URL, MAX_PAGES, clinical_trials_params, fda_params
from impurity_leads.adapters.company_site import CompanySiteAdapter
from impurity_leads.adapters.common_crawl import CommonCrawlAdapter, IndexNameCache
from impurity_leads.contacts.discovery import contact_candidate_urls
from impurity_leads.contacts.extract import extract_contacts_from_html
from impurity_leads.contacts.models import ContactCandidate
from impurity_leads.contacts.pipeline import enrich_contact_candidates
from impurity_leads.crawling.robots import RobotsPolicy
from impurity_leads.crawling.sitemap import parse_sitemap
from impurity_leads.execution.http import CrawlClient, HostGate
from impurity_leads.execution.retry import TaskFailure, classify_error, DatabaseUnavailable, InterruptedTask
from impurity_leads.models import Opportunity
from impurity_leads.seeds import relevant_candidate_urls
from impurity_leads.zero_cost import ProviderUsage


# Each child sitemap costs a paced request; the newest ones carry current pages.
MAX_CHILD_SITEMAPS = 5


class CrawlHandlers:
    def __init__(self, settings, *, client_factory=None, reporter=None, opportunities=None, provider_usage: ProviderUsage | None = None):
        self.opportunities=opportunities or []
        self.settings=settings
        self.gate=HostGate(settings.per_domain_delay_seconds)
        self.client_factory=client_factory
        self.reporter=reporter
        self.provider_usage=provider_usage
        self.common_crawl_index=IndexNameCache()
    def client(self,ctx):
        return nullcontext(self.client_factory(ctx)) if self.client_factory else CrawlClient(ctx,self.settings,self.gate,usage=self.provider_usage)
    def structured(self,ctx):
        from impurity_leads.cli import _structured_headers
        if ctx.checkpoint.get('fetched'):
            return ctx.result
        source=ctx.task['identifier']
        with self.client(ctx) as client:
            records=[]
            if source=='clinical_trials':
                adapter=ClinicalTrialsAdapter();token=None
                for _ in range(MAX_PAGES):
                    payload=self._structured_page(client,CLINICAL_TRIALS_URL,clinical_trials_params(token))
                    for study in payload.get('studies',[]): records.extend(adapter.parse(study))
                    token=payload.get('nextPageToken')
                    if not token: break
            else:
                adapter=FDAAdapter()
                for page in range(MAX_PAGES):
                    results=self._structured_page(client,FDA_URL,fda_params(page)).get('results',[])
                    for result in results: records.extend(adapter.parse(result))
                    if len(results)<FDA_PAGE_SIZE: break
            result={'records':[r.model_dump(mode='json') for r in records]}
            ctx.save_progress({'fetched':True},result)
            return result
    def _structured_page(self,client,url,params):
        from impurity_leads.cli import _structured_headers
        response=client.get(url,params=params,headers=_structured_headers(self.settings))
        try: response.raise_for_status()
        except httpx.HTTPStatusError as error: raise classify_error(error) from None
        return response.json()
    def _robots(self,client,domain):
        base=f'https://{domain}'
        response=client.get(base+'/robots.txt',headers={'User-Agent':self.settings.user_agent})
        if response.status_code in {401,403}: raise TaskFailure(f'robots_{response.status_code}',skipped=True)
        if response.status_code==404: text=''
        else:
            response.raise_for_status();text=response.text
        policy=RobotsPolicy.from_text(text,base,self.settings.user_agent)
        self.gate.set_delay(base,policy.crawl_delay())
        return policy
    def _sitemap(self,client,url,policy,required=False):
        if not policy.can_fetch(url):return None
        response=client.get(url,headers={'User-Agent':self.settings.user_agent})
        if response.status_code!=200:
            if required and response.status_code not in {401,403,404,410}:response.raise_for_status()
            return None
        try:return parse_sitemap(response.content)
        except Exception:return None
    def _sitemap_urls(self,client,domain,policy):
        """Root sitemap, or the newest children of a sitemap index (one level), newest pages first."""
        root=self._sitemap(client,f'https://{domain}/sitemap.xml',policy,required=True)
        if root is None:return []
        if not root.is_index:return root.locations()
        wanted=domain.lower().removeprefix('www.')
        entries=[]
        children=[u for u in root.locations() if (urlparse(u).hostname or '').removeprefix('www.')==wanted]
        for child in children[:MAX_CHILD_SITEMAPS]:
            sitemap=self._sitemap(client,child,policy)
            if sitemap and not sitemap.is_index:entries.extend(sitemap.entries)
        return type(root)(is_index=False,entries=tuple(entries)).locations()
    def _discovery(self,client,domain,policy,contact=False):
        sitemap=self._sitemap_urls(client,domain,policy)
        common=[]
        try:
            adapter=CommonCrawlAdapter(client=client,user_agent=self.settings.user_agent,
                max_urls_per_domain=12 if contact else 10,sleep_fn=lambda _:None,
                index_cache=self.common_crawl_index)
            if contact:
                common=adapter.discover(domain,url_terms=('leadership','management','team','people','about','research','science','rd','r-and-d','analytical','development','quality','regulatory','procurement','sourcing','contact','press','news','investor'))
            else:common=adapter.discover(domain)
        except (DatabaseUnavailable,InterruptedTask):raise
        except Exception as error:
            failure = classify_error(error)
            if failure.retryable:
                failure.domain = 'index.commoncrawl.org'
                raise failure from None
            if self.reporter:self.reporter.emit({'event':'source_skipped','source':'common_crawl','domain':domain,'status':'skipped','error':failure.code})
        return contact_candidate_urls([*sitemap,*common],domain,limit=12) if contact else relevant_candidate_urls(domain,sitemap,common,cap=15)
    def _pages(self,ctx,contact=False):
        domain=ctx.task['domain']
        with self.client(ctx) as client:
            policy=self._robots(client,domain)
            cp=dict(ctx.checkpoint)
            if 'urls' not in cp:
                cp.update(urls=self._discovery(client,domain,policy,contact),index=0,
                          observed_at=datetime.now(timezone.utc).isoformat())
                ctx.save_progress(cp,ctx.result)
            for index in range(cp.get('index',0),len(cp['urls'])):
                ctx.check()
                url=cp['urls'][index]
                html=None;modified=None
                if policy.can_fetch(url):
                    response=client.get(url,headers={'User-Agent':self.settings.user_agent})
                    if response.status_code not in {401,403,404,410}:
                        response.raise_for_status();html=response.text;modified=response.headers.get('Last-Modified')
                yield cp,index,url,html,modified
    def company(self,ctx):
        records=list(ctx.result.get('records',[]))
        seed_indexes=list(ctx.result.get('record_seed_indexes',[]))
        adapter=CompanySiteAdapter()
        for cp,index,url,html,modified in self._pages(ctx):
            if html:
                for seed in cp['seeds']:
                    parsed = adapter.parse_html(url,html,seed['company_name'],seed['molecules'],last_modified=modified)
                    records.extend(r.model_dump(mode='json') for r in parsed)
                    seed_indexes.extend([cp['seeds'].index(seed)] * len(parsed))
            cp={**cp,'index':index+1}
            ctx.save_progress(cp,{'records':records,'record_seed_indexes':seed_indexes})
        return {'records':records,'record_seed_indexes':seed_indexes}
    def contacts(self,ctx):
        wanted=set(ctx.checkpoint['opportunity_keys'])
        opportunities=[o for o in self.opportunities if o.company_name+'|'+o.molecule_name in wanted]
        candidates=dict(ctx.result.get('candidates',{}))
        for cp,index,url,html,_ in self._pages(ctx,True):
            if html:
                for name in dict.fromkeys(o.company_name for o in opportunities):
                    items=extract_contacts_from_html(url,html,name,datetime.fromisoformat(cp['observed_at']))
                    candidates.setdefault(name,[]).extend(i.model_dump(mode='json') for i in items)
            cp={**cp,'index':index+1}
            ctx.save_progress(cp,{'candidates':candidates})
        contacts=[]
        observed=ctx.checkpoint.get('observed_at')
        now=datetime.fromisoformat(observed) if observed else datetime.now(timezone.utc)
        for opportunity in opportunities:
            ranked=enrich_contact_candidates(opportunity,ctx.task['domain'],
                [ContactCandidate.model_validate(i) for i in candidates.get(opportunity.company_name,[])],now)
            contacts.append({'company_name':opportunity.company_name,'molecule_name':opportunity.molecule_name,
                             'ranked':[r.model_dump(mode='json') for r in ranked]})
        return {'contacts':contacts}
