from types import SimpleNamespace

import httpx
import pytest

from impurity_leads.config import Settings
from impurity_leads.execution import daily
from impurity_leads.execution.crawl import CrawlHandlers
from impurity_leads.execution.retry import TaskFailure
from impurity_leads.pipeline import process_records
from impurity_leads.storage.memory import MemoryLeadStore
from impurity_leads.models import SourceRecord


def record(name):
    return SourceRecord(source_name='test', source_type='site', fetched_at='2026-09-05T00:00:00Z', source_url=f'https://{name}.com/tender',
                        company_name_raw=name, molecule_name_raw='Drug X', signal_text='request for quotation impurity reference standard').model_dump(mode='json')


def test_reconstruction_preserves_structured_then_original_seed_order():
    a, b, c, d = [record(name) for name in ('Structured', 'SeedA', 'SeedB', 'SeedC')]
    rows = [
        {'stage':'company_crawling','task_key':'company:000:a','result_json':{'records':[b,d,b,d], 'record_seed_indexes':[0,2,0,2]}},
        {'stage':'company_crawling','task_key':'company:001:b','result_json':{'records':[c], 'record_seed_indexes':[1]}},
        {'stage':'structured_sources','task_key':'source:clinical_trials','result_json':{'records':[a]}},
    ]
    actual = daily.collected_records(rows)
    expected = [SourceRecord.model_validate(item) for item in [a,b,b,c,d,d]]
    assert actual == expected
    assert process_records(actual,MemoryLeadStore()) == process_records(expected,MemoryLeadStore())


def test_common_crawl_retry_after_reaches_task_scheduler():
    handlers=CrawlHandlers(Settings())
    def respond(request):
        if request.url.path=='/sitemap.xml': return httpx.Response(404)
        return httpx.Response(429,headers={'Retry-After':'137'})
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        with pytest.raises(TaskFailure) as error:
            handlers._discovery(client,'example.com',SimpleNamespace(can_fetch=lambda _:True))
    assert error.value.retryable
    assert error.value.retry_after == 137
    assert error.value.domain == 'index.commoncrawl.org'


def test_export_run_reads_completed_outputs_without_claiming_or_crawling(monkeypatch,tmp_path):
    class ReadOnlyStore:
        def load_run(self,run_id=None):
            assert run_id=='finished-run'
            self.run={'id':run_id,'status':'completed'}
            return self.run
        def tasks(self):
            return [{'stage':'processing_scoring','status':'completed','result_json':{'opportunities':[]}},
                    {'stage':'contact_enrichment','result_json':{'contacts':[]}}]
    monkeypatch.setattr(daily,'create_task_store',lambda _:ReadOnlyStore())
    assert daily.export_run(Settings(),tmp_path,'finished-run') == 0
    assert (tmp_path/'exports/opportunities-finished-run.csv').exists()
    assert (tmp_path/'exports/opportunities-finished-run.xlsx').exists()
    assert daily.export_run(Settings(),tmp_path,'finished-run') == 0


def test_export_run_rejects_unfinished_run(monkeypatch,tmp_path):
    store=SimpleNamespace(load_run=lambda _: {'id':'unfinished','status':'paused'})
    monkeypatch.setattr(daily,'create_task_store',lambda _:store)
    assert daily.export_run(Settings(),tmp_path,'unfinished') == 1
    assert not (tmp_path/'exports').exists()


def test_export_run_cli_routes_optional_identifier(monkeypatch):
    from impurity_leads import cli
    calls=[]
    monkeypatch.setattr(daily,'export_run',lambda settings,root,run_id=None:calls.append(run_id) or 0)
    assert cli.main(['export-run','finished-run']) == 0
    assert cli.main(['export-run']) == 0
    assert calls == ['finished-run',None]
