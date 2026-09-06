from impurity_leads import cli
from impurity_leads.config import Settings, load_settings


def test_workers_and_fresh_reach_daily(monkeypatch):
    seen=[]
    monkeypatch.setattr(cli,'run_daily',lambda workers=6,fresh=False:seen.append((workers,fresh)) or 0)
    assert cli.main(['run-daily','--workers','6','--fresh'])==0
    assert seen==[(6,True)]


def test_status_command_read_only_dispatch(monkeypatch):
    from impurity_leads.execution import daily
    seen=[]
    monkeypatch.setattr(daily,'status',lambda settings:seen.append(settings) or 0)
    assert cli.main(['status'])==0
    assert len(seen)==1


def test_configurable_timeout_and_drain(monkeypatch):
    monkeypatch.setenv('CRAWLER_CONNECT_TIMEOUT_SECONDS','7')
    monkeypatch.setenv('CRAWLER_SHUTDOWN_DRAIN_SECONDS','2')
    settings=load_settings()
    assert settings.connect_timeout_seconds==7 and settings.shutdown_drain_seconds==2
