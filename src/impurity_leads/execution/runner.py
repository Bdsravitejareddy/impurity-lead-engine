"""Bounded daemon workers. Supabase, not threads, owns execution state."""
import threading
import time
from collections import deque
from queue import Queue, Empty

from impurity_leads.execution.retry import DatabaseUnavailable, InterruptedTask, TaskFailure, classify_error, retry_delay
from impurity_leads.execution.tasks import TERMINAL, validate_payload


class Context:
    def __init__(self, runner, task):
        self.runner = runner
        self.store = runner.store
        self.task = task
        self.checkpoint = task.get('checkpoint_json') or {}
        self.result = task.get('result_json') or {}
        self.started = time.monotonic()
    def check(self):
        if self.runner.stop.is_set() or time.monotonic() >= self.runner.deadline:
            raise InterruptedTask()
        if time.monotonic() - self.started >= self.runner.settings.task_timeout_seconds:
            raise TaskFailure('task_timeout', retryable=True)
    def before_request(self):
        self.check()
        if self.store.renew(self.task) is False:
            raise DatabaseUnavailable("lease_lost")
    def save_progress(self, checkpoint, result):
        validate_payload(checkpoint)
        validate_payload(result, result=True)
        self.store.save(self.task, 'running', checkpoint, result)
        self.checkpoint, self.result = checkpoint, result


class Runner:
    def __init__(self, store, settings, workers=6, stop=None, reporter=None, deadline=None):
        if not 1 <= workers <= 32:
            raise ValueError('workers must be between 1 and 32')
        self.store, self.settings, self.workers = store, settings, workers
        self.stop = stop or threading.Event()
        self.reporter = reporter
        self.deadline = deadline or time.monotonic() + settings.run_deadline_minutes * 60 - settings.shutdown_drain_seconds
        self.active = {}
        self.results = Queue()
        self.connectivity_failures = deque()
        self.paused_reason = None
    def emit(self, **event):
        if self.reporter:
            self.reporter.emit(event)
    def _worker(self, task, handler):
        ctx = Context(self, task)
        status, error, delay = 'completed', None, 0
        try:
            result = handler(ctx)
            validate_payload(result, result=True)
            ctx.result = result
        except InterruptedTask:
            status = 'pending'
        except DatabaseUnavailable:
            self.stop.set()
            self.paused_reason = 'database_unavailable'
            self.results.put((task, None))
            return
        except Exception as exc:
            failure = classify_error(exc)
            error = failure.code
            if getattr(failure, 'domain', None):
                task['_error_domain'] = failure.domain
            status = 'skipped' if failure.skipped else 'retryable_failed' if failure.retryable and task['attempt_count'] < 3 else 'permanent_failed'
            if status == 'retryable_failed':
                delay = retry_delay(task['attempt_count'], failure, self.settings.retry_base_seconds, self.settings.retry_cap_seconds)
        try:
            domain = task.get('_error_domain') or task.get('domain')
            if domain and status in {'completed', 'retryable_failed', 'permanent_failed'}:
                transient = error in {'dns_error','connect_error','timeout','http_429','http_503','http_502','http_504'}
                if status == 'completed' or transient:
                    self.store.domain_result(domain, status == 'completed', error, self.settings.domain_cooldown_seconds if transient and task['attempt_count'] >= 2 else 0, task=task)
            self.store.save(task, status, ctx.checkpoint, ctx.result, error=error, delay=delay, duration=time.monotonic()-ctx.started)
            self.emit(event='task_finished', source=task.get('identifier',''),domain=task.get('domain'),stage=task['stage'],status=status,error=error,attempt=task['attempt_count'])
        except DatabaseUnavailable:
            self.stop.set()
            self.paused_reason = 'database_unavailable'
        finally:
            self.results.put((task, error))
    def _collect(self):
        while True:
            try:
                task,error = self.results.get_nowait()
            except Empty:
                break
            self.active.pop(task['id'],None)
            if error in {'dns_error','connect_error','timeout'}:
                if task.get('_error_domain') in {'index.commoncrawl.org', 'clinicaltrials.gov', 'api.fda.gov'}:
                    continue
                now=time.monotonic()
                self.connectivity_failures.append((now, task.get('_error_domain') or task.get('domain') or task.get('identifier')))
                while self.connectivity_failures and self.connectivity_failures[0][0]<now-self.settings.outage_window_seconds:
                    self.connectivity_failures.popleft()
                if len({domain for _,domain in self.connectivity_failures})>=self.settings.outage_domain_threshold:
                    self.paused_reason='network_outage'; self.stop.set()
    def run_stage(self, stage, handler):
        heartbeat = 0.0
        next_snapshot = 0.0
        rows = []
        while not self.stop.is_set() and time.monotonic()<self.deadline:
            self._collect()
            if self.stop.is_set(): break
            try:
                if time.monotonic() >= heartbeat:
                    self.store.heartbeat()
                    for task, _ in list(self.active.values()): self.store.renew(task)
                    heartbeat=time.monotonic()+self.settings.heartbeat_seconds
                while len(self.active)<self.workers and not self.stop.is_set():
                    task=self.store.claim(stage)
                    if not task: break
                    worker=threading.Thread(target=self._worker,args=(task,handler),daemon=True)
                    self.active[task['id']]=(task,worker)
                    worker.start()
                if time.monotonic() >= next_snapshot or not self.active:
                    rows=getattr(self.store, 'snapshot', self.store.tasks)()
                    next_snapshot=time.monotonic()+1.0
                    if self.reporter: self.reporter.render(self.store.run,rows)
                stage_rows=[t for t in rows if t['stage']==stage]
                if not self.active and all(t['status'] in TERMINAL for t in stage_rows): return True
            except DatabaseUnavailable:
                self.paused_reason='database_unavailable';self.stop.set();break
            self.stop.wait(self.settings.scheduler_poll_seconds)
        self.stop.set()
        drain_until=time.monotonic()+self.settings.shutdown_drain_seconds
        while self.active and time.monotonic()<drain_until:
            self._collect()
            time.sleep(min(.05,max(0,drain_until-time.monotonic())))
        self.emit(event='run_paused',status='paused',error=self.paused_reason or 'interrupted',stage=stage)
        return False
