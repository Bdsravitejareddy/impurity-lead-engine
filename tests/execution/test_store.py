import pytest
from impurity_leads.storage.task_store import SupabaseTaskStore
from impurity_leads.execution.retry import DatabaseUnavailable
from impurity_leads.config import Settings


class Client:
    def __init__(self): self.calls=[]
    def rpc(self,name,params):
        self.calls.append((name,params)); self.value={'id':'run','coordinator_token':'claim'} if name=='crawl_begin' else None
        return self
    def execute(self): return type('Response',(),{'data':self.value})()


def test_rpc_claim_uses_coordinator_identity():
    client=Client();store=SupabaseTaskStore(lambda:client,Settings())
    store.begin('fingerprint','worker',False,{})
    store.claim('company_crawling')
    name,p=client.calls[-1]
    assert name=='crawl_claim'
    assert p['p_run_id']=='run' and p['p_coordinator_token']=='claim'
    assert p['p_stage']=='company_crawling'


def test_database_error_does_not_expose_exception():
    class Broken:
        def rpc(self,*a): raise RuntimeError('secret-auth-header')
    store=SupabaseTaskStore(lambda:Broken(),Settings())
    with pytest.raises(DatabaseUnavailable) as e:store.begin('f','o',False,{})
    assert 'secret' not in str(e.value)
