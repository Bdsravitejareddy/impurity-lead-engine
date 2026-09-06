"""Service-role durable execution. No local fallback and no raw DB errors."""
import threading

from impurity_leads.execution.retry import DatabaseUnavailable
from impurity_leads.execution.tasks import validate_payload


class SupabaseTaskStore:
    def __init__(self, client_factory, settings):
        self.client_factory = client_factory
        self.settings = settings
        self.local = threading.local()
        self.run = {}
        self.owner = ''
    @property
    def client(self):
        if not hasattr(self.local,'client'):
            self.local.client = self.client_factory()
        return self.local.client
    def _rpc(self,name,**params):
        try:
            data=self.client.rpc(name,params).execute().data
            return data[0] if isinstance(data,list) and len(data)==1 else data
        except Exception:
            raise DatabaseUnavailable('execution_store_unavailable') from None
    def _identity(self):
        return {'p_run_id':self.run['id'], 'p_coordinator_token':self.run['coordinator_token']}
    def begin(self,fingerprint,owner,fresh,config):
        self.owner=owner
        self.run=self._rpc('crawl_begin',p_fingerprint=fingerprint,p_owner=owner,p_fresh=fresh,p_config=config,p_lease_seconds=self.settings.lease_seconds)
        if not self.run:
            raise DatabaseUnavailable('coordinator_unavailable')
        return self.run
    def plan(self,tasks):
        return self._rpc('crawl_plan',**self._identity(),p_tasks=tasks)
    def claim(self,stage):
        return self._rpc('crawl_claim',**self._identity(),p_stage=stage,p_owner=self.owner,p_lease_seconds=self.settings.lease_seconds)
    def heartbeat(self):
        return self._rpc('crawl_heartbeat',**self._identity(),p_lease_seconds=self.settings.lease_seconds)
    def renew(self,task):
        return self._rpc('crawl_renew',p_task_id=task['id'],p_token=task['lease_token'],p_coordinator_token=self.run['coordinator_token'],p_lease_seconds=self.settings.lease_seconds)
    def save(self,task,status,checkpoint,result,error=None,delay=0,duration=0):
        validate_payload(checkpoint);validate_payload(result,result=True)
        return self._rpc('crawl_save',p_task_id=task['id'],p_token=task['lease_token'],p_coordinator_token=self.run['coordinator_token'],p_status=status,p_checkpoint=checkpoint,p_result=result,p_error=error,p_delay_seconds=delay,p_duration_seconds=duration)
    def finish(self,status,stage,metrics):
        value=self._rpc('crawl_finish_run',**self._identity(),p_status=status,p_stage=stage,p_metrics=metrics)
        if isinstance(value,dict):self.run.update(value)
    def domain_result(self,domain,success,error=None,cooldown=0,*,task):
        return self._rpc('crawl_domain_result',p_domain=domain,p_success=success,p_error=error,p_cooldown_seconds=cooldown,p_task_id=task['id'],p_token=task['lease_token'],p_coordinator_token=self.run['coordinator_token'])
    def publish(self,task,rows,checkpoint):
        validate_payload(checkpoint)
        return self._rpc('crawl_publish',p_task_id=task['id'],p_token=task['lease_token'],p_coordinator_token=self.run['coordinator_token'],p_rows=rows,p_checkpoint=checkpoint)
    def snapshot(self):
        return self.tasks(summary=True)
    def tasks(self, summary=False):
        try:
            rows=[];offset=0
            while True:
                batch=self.client.table('crawl_tasks').select('id,task_key,stage,status,attempt_count,domain,identifier,lease_expires_at,started_at,completed_at,updated_at,duration_seconds,next_eligible_at' if summary else '*').eq('run_id',self.run['id']).order('task_key').range(offset,offset+199).execute().data
                rows.extend(batch)
                if len(batch)<200:return rows
                offset+=200
        except Exception:
            raise DatabaseUnavailable('execution_store_unavailable') from None
    def latest(self):
        try:
            rows=self.client.table('crawl_runs').select('*').eq('source_adapter','daily').order('started_at',desc=True).limit(1).execute().data
            self.run=rows[0] if rows else {}
            return self.run
        except Exception:
            raise DatabaseUnavailable('execution_store_unavailable') from None

    def load_run(self, run_id=None):
        try:
            query = self.client.table('crawl_runs').select('*')
            if run_id:
                query = query.eq('id', run_id)
            rows = query.order('started_at', desc=True).limit(1).execute().data
            self.run = rows[0] if rows else {}
            return self.run
        except Exception:
            raise DatabaseUnavailable('execution_store_unavailable') from None


def create_task_store(settings):
    if not settings.supabase_url or not settings.supabase_secret_key:
        raise DatabaseUnavailable('supabase_required')
    from supabase import create_client
    from supabase.lib.client_options import SyncClientOptions
    def factory():
        # Supabase transport configuration stays independent of crawl transport.
        return create_client(settings.supabase_url,settings.supabase_secret_key,
            options=SyncClientOptions(postgrest_client_timeout=settings.request_timeout_seconds))
    return SupabaseTaskStore(factory,settings)
