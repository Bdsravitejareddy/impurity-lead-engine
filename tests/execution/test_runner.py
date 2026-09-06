import threading
import time

from impurity_leads.execution.runner import Runner
from impurity_leads.execution.retry import TaskFailure
from impurity_leads.execution.tasks import task
from impurity_leads.config import Settings
from .support import MemoryTasks


def test_worker_count_and_results():
    store=MemoryTasks(); store.plan([task(str(i),'company_crawling',domain=f'd{i}.test') for i in range(12)])
    active=peak=0
    lock=threading.Lock()
    def handle(ctx):
        nonlocal active,peak
        with lock: active+=1; peak=max(peak,active)
        time.sleep(.02)
        with lock: active-=1
        return {'value':ctx.task['task_key']}
    runner=Runner(store,Settings(),workers=6)
    assert runner.run_stage('company_crawling',handle)
    assert peak==6
    assert all(t['status']=='completed' for t in store.tasks())


def test_three_total_attempts_across_runner_restarts():
    store=MemoryTasks();store.plan([task('x','test')])
    def fail(ctx): raise TaskFailure('http_503',retryable=True)
    settings=Settings(retry_base_seconds=0, scheduler_poll_seconds=.001)
    assert Runner(store,settings).run_stage('test',fail)
    assert store.tasks()[0]['attempt_count']==3
    assert store.tasks()[0]['status']=='permanent_failed'
    Runner(store,settings).run_stage('test',fail)
    assert store.tasks()[0]['attempt_count']==3


def test_stop_does_not_wait_indefinitely_for_native_worker():
    store=MemoryTasks();store.plan([task('x','test'),task('y','test')])
    stop=threading.Event(); entered=threading.Event();release=threading.Event()
    def blocked(ctx): entered.set();release.wait();return {}
    runner=Runner(store,Settings(shutdown_drain_seconds=.03,scheduler_poll_seconds=.001),workers=1,stop=stop)
    thread=threading.Thread(target=lambda:runner.run_stage('test',blocked))
    thread.start();assert entered.wait(1);stop.set();thread.join(.5)
    assert not thread.is_alive()
    assert store.tasks()[1]['attempt_count']==0
    release.set()


def test_partial_output_survives_retry():
    store=MemoryTasks();store.plan([task('x','test')])
    def handle(ctx):
        if ctx.task['attempt_count']==1:
            ctx.save_progress({'index':1},{'items':['first']})
            raise TaskFailure('http_503',retryable=True)
        assert ctx.checkpoint=={'index':1}
        return {'items':ctx.result['items']+['second']}
    assert Runner(store,Settings(retry_base_seconds=0)).run_stage('test',handle)
    assert store.tasks()[0]['result_json']=={'items':['first','second']}


def test_shared_source_failure_is_not_a_machine_wide_outage():
    store=MemoryTasks();store.plan([task(str(i),'company_crawling',domain=f'd{i}.test') for i in range(6)])
    stop=threading.Event()
    def fail(ctx):
        failure=TaskFailure('connect_error',retryable=True)
        failure.domain='index.commoncrawl.org'
        # Stop after this bounded first wave; only actual origins should count.
        if ctx.task['task_key']=='5':stop.set()
        raise failure
    runner=Runner(store,Settings(shutdown_drain_seconds=.1),workers=6,stop=stop)
    runner.run_stage('company_crawling',fail)
    assert runner.paused_reason != 'network_outage'
    assert all(domain=='index.commoncrawl.org' for domain,_,_ in store.domain_events)
