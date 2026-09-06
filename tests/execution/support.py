"""Explicit offline execution-store double; never used by live code."""
import copy
import threading
import time
import uuid

from impurity_leads.execution.tasks import TERMINAL


class MemoryTasks:
    def __init__(self):
        self.lock = threading.RLock()
        self.rows = []
        self.run = {'id':'offline-run', 'status':'running', 'metrics_json':{}, 'config_json':{}}
        self.domain_events = []
    def plan(self, tasks):
        with self.lock:
            for t in tasks:
                if any(r['task_key']==t['task_key'] for r in self.rows): continue
                self.rows.append(dict(t,id=str(uuid.uuid4()), status='pending',attempt_count=0,result_json={}, next_due=0))
    def tasks(self):
        with self.lock: return copy.deepcopy(sorted(self.rows,key=lambda r:r['task_key']))
    def claim(self,stage):
        with self.lock:
            for r in self.rows:
                if r['stage']==stage and r['status'] not in TERMINAL|{'running'} and r['next_due']<=time.monotonic():
                    if r['attempt_count']>=3:
                        r['status']='permanent_failed'; continue
                    r.update(status='running',attempt_count=r['attempt_count']+1,lease_token=str(uuid.uuid4()))
                    return copy.deepcopy(r)
    def save(self,t,status,checkpoint,result,error=None,delay=0,duration=0):
        with self.lock:
            r=next(r for r in self.rows if r['id']==t['id'])
            assert r['lease_token']==t['lease_token'] and r['status']=='running'
            r.update(status=status, checkpoint_json=copy.deepcopy(checkpoint),result_json=copy.deepcopy(result),last_error_code=error,next_due=time.monotonic()+delay,duration_seconds=duration)
            return copy.deepcopy(r)
    def renew(self,t): pass
    def heartbeat(self): pass
    def finish(self,status,stage,metrics): self.run.update(status=status,current_stage=stage,metrics_json=metrics)
    def domain_result(self,domain,success,error=None,cooldown=0,*,task=None): self.domain_events.append((domain,success,error))
