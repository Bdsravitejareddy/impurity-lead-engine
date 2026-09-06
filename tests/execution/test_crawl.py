import json
from pathlib import Path
import httpx
import pytest
from impurity_leads.execution.crawl import CrawlHandlers
from impurity_leads.execution.retry import TaskFailure
from impurity_leads.config import Settings


class Ctx:
    def __init__(self,stage='company_crawling'):
        self.task={'task_key':'company:example.com','stage':stage,'domain':'example.com','identifier':'Example Pharma'}
        self.checkpoint={'seeds':[{'company_name':'Example Pharma','domain':'example.com','molecules':['Drug X']}]}
        self.result={}
    def check(self): pass
    def save_progress(self,cp,result): self.checkpoint=cp;self.result=result


def test_company_resumes_after_saved_page_without_refetching_it():
    calls=[];failed=[False]
    def handler(req):
        calls.append(req.url.path)
        if req.url.path=='/robots.txt':return httpx.Response(404)
        if req.url.path=='/sitemap.xml':return httpx.Response(200,text='<urlset><url><loc>https://example.com/jobs/1</loc></url><url><loc>https://example.com/jobs/2</loc></url></urlset>')
        if req.url.path=='/jobs/2' and not failed[0]:
            failed[0]=True;raise httpx.ReadTimeout('private')
        if '/jobs/' in req.url.path:return httpx.Response(200,text=Path('tests/fixtures/company_job.html').read_text())
        return httpx.Response(404)
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        handlers=CrawlHandlers(Settings(),client_factory=lambda ctx:client)
        ctx=Ctx()
        with pytest.raises(httpx.ReadTimeout):handlers.company(ctx)
        assert ctx.checkpoint['index']==1
        records=handlers.company(ctx)['records']
    assert records
    assert calls.count('/jobs/1')==1


def test_structured_403_is_visible_terminal_skip():
    with httpx.Client(transport=httpx.MockTransport(lambda r:httpx.Response(403))) as client:
        handlers=CrawlHandlers(Settings(),client_factory=lambda ctx:client)
        ctx=Ctx('structured_sources');ctx.task['identifier']='clinical_trials'
        with pytest.raises(TaskFailure) as failure:handlers.structured(ctx)
    assert failure.value.skipped and not failure.value.retryable
    assert failure.value.code=='http_403'


def test_extracted_candidates_match_existing_contact_pipeline():
    from impurity_leads.contacts.pipeline import enrich_opportunity_contacts, enrich_contact_candidates
    from impurity_leads.contacts.extract import extract_contacts_from_html
    from impurity_leads.models import Opportunity
    from datetime import datetime,timezone
    now=datetime(2026,9,5,tzinfo=timezone.utc)
    opportunity=Opportunity(company_name='Example Pharma',molecule_name='Drug X',score=90,priority='HOT',likely_need_type=['nitrosamine/NDSRI'],rationale='test')
    html=Path('tests/fixtures/contact_leadership.html').read_text();url='https://example.com/leadership'
    expected=enrich_opportunity_contacts(opportunity,'example.com',[(url,html)],now=now)
    candidates=extract_contacts_from_html(url,html,'Example Pharma',now)
    assert enrich_contact_candidates(opportunity,'example.com',candidates,now)==expected
