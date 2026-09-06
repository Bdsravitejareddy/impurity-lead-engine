import json
from pathlib import Path
import httpx
import pytest
from impurity_leads.execution.daily import execute_run
from impurity_leads.config import Settings
from impurity_leads.seeds import CompanySeed
from .support import MemoryTasks


def fixture_client(ctx):
    def handler(request):
        host=request.url.host;path=request.url.path
        if host=='clinicaltrials.gov':return httpx.Response(403)
        if host=='api.fda.gov':return httpx.Response(200,json={'results':[json.loads(Path('tests/fixtures/fda_record.json').read_text())]})
        if path=='/robots.txt':return httpx.Response(404)
        if path=='/sitemap.xml':return httpx.Response(200,text=f'<urlset><url><loc>https://{host}/jobs/1</loc></url><url><loc>https://{host}/leadership</loc></url></urlset>')
        if path=='/jobs/1':return httpx.Response(200,text=Path('tests/fixtures/company_job.html').read_text())
        if path=='/leadership':return httpx.Response(200,text=Path('tests/fixtures/contact_leadership.html').read_text())
        return httpx.Response(404)
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_daily_graph_persists_and_exports_without_repeating_completed_tasks(tmp_path):
    store=MemoryTasks();store.published=[]
    store.publish=lambda task,rows,checkpoint:store.published.extend(rows)
    seeds=[CompanySeed('Example Pharma','example.com',['Drug X'])]
    settings=Settings(per_domain_delay_seconds=0,scheduler_poll_seconds=.001)
    assert execute_run(store,settings,seeds,tmp_path,client_factory=fixture_client,workers=6)==0
    scoring=next(t for t in store.tasks() if t['stage']=='processing_scoring')
    assert scoring['result_json']['signals']
    assert scoring['result_json']['opportunities']
    count=len(store.published)
    assert count>0 and list(tmp_path.glob('*.csv'))
    def forbidden(ctx):raise AssertionError('completed network task repeated')
    assert execute_run(store,settings,seeds,tmp_path,client_factory=forbidden)==0
    assert len(store.published)==count


def test_live_daily_requires_supabase_and_never_falls_back(tmp_path):
    from impurity_leads.execution.daily import run_daily
    assert run_daily(Settings(),tmp_path,workers=1)==2
