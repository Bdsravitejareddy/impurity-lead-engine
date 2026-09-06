import os
from pathlib import Path
import select
import signal
import subprocess
import sys
import threading

import pytest

from impurity_leads.config import Settings
from impurity_leads.execution.runner import Runner
from impurity_leads.execution.retry import TaskFailure
from impurity_leads.execution.tasks import task
from .support import MemoryTasks


@pytest.mark.parametrize('sig',[signal.SIGINT,signal.SIGTERM])
def test_signal_shutdown_exits_with_blocked_daemon_worker(sig):
    code='''
import signal, threading
from impurity_leads.config import Settings
from impurity_leads.execution.runner import Runner
from impurity_leads.execution.tasks import task
from tests.execution.support import MemoryTasks
stop=threading.Event()
for sig in (signal.SIGINT,signal.SIGTERM):signal.signal(sig,lambda *_:stop.set())
store=MemoryTasks();store.plan([task('blocked','test')])
def handler(ctx):
    print('ready',flush=True)
    threading.Event().wait()
runner=Runner(store,Settings(shutdown_drain_seconds=.05,scheduler_poll_seconds=.001),workers=1,stop=stop)
assert not runner.run_stage('test',handler)
print('resumable',flush=True)
'''
    env=dict(os.environ,PYTHONPATH=str(Path.cwd())+os.pathsep+str(Path.cwd()/'src'))
    process=subprocess.Popen([sys.executable,'-c',code],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,env=env)
    try:
        assert select.select([process.stdout],[],[],5)[0]
        assert process.stdout.readline().strip()=='ready'
        process.send_signal(sig)
        stdout,stderr=process.communicate(timeout=2)
        assert process.returncode==0 and 'resumable' in stdout
    finally:
        if process.poll() is None:process.kill();process.wait()


def test_widespread_outage_pauses_queue_before_exhausting_domains():
    store=MemoryTasks();store.plan([task(str(i),'company_crawling',domain=f'company{i}.test') for i in range(100)])
    def fail(ctx):raise TaskFailure('connect_error',retryable=True)
    runner=Runner(store,Settings(shutdown_drain_seconds=.05,scheduler_poll_seconds=.001),workers=6)
    assert not runner.run_stage('company_crawling',fail)
    assert runner.paused_reason=='network_outage'
    assert sum(t['attempt_count'] for t in store.tasks())<=6
    assert sum(t['status']=='pending' for t in store.tasks())>=94
