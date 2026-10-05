from datetime import datetime
import json
import os
from pathlib import Path
import time
from types import SimpleNamespace
import mojito
import pytest

from core.broker.auth import authenticated_client
from apps.system import workflow as wf
from apps.system.operations import finish_session
from apps.system.supervisor import progress_stalled


def test_auth_tokens_are_scoped_private_and_not_pickle(monkeypatch, tmp_path):
    monkeypatch.setenv('KIS_TOKEN_CACHE_DIR',str(tmp_path))
    calls=[]
    def post(url,**kw):
        calls.append((url,kw))
        return SimpleNamespace(raise_for_status=lambda:None,json=lambda:{'access_token':'test-token','expires_in':3600})
    monkeypatch.setattr('core.broker.auth.requests.post',post)
    settings=dict(api_key='key',api_secret='secret',acc_no='12345678-01',mock=True)
    first=authenticated_client(mojito.KoreaInvestment,**settings)
    second=authenticated_client(mojito.KoreaInvestment,**settings)
    assert first.access_token==second.access_token=='Bearer test-token'
    assert len(calls)==1 and calls[0][1]['timeout']==10
    authenticated_client(mojito.KoreaInvestment,**dict(settings,mock=False))
    assert len(calls)==2
    files=list(tmp_path.glob('*.json'))
    assert len(files)==2
    for file in files:
        assert 'secret' not in file.read_text() and 'api_key' not in file.read_text()
        if os.name!='nt':assert file.stat().st_mode&0o777==0o600
    assert not (tmp_path/'token.dat').exists()


def test_auth_dependency_errors_never_include_credentials(monkeypatch,tmp_path):
    monkeypatch.setenv('KIS_TOKEN_CACHE_DIR',str(tmp_path))
    def fail(*a,**k):raise RuntimeError('private-secret-key')
    monkeypatch.setattr('core.broker.auth.requests.post',fail)
    with pytest.raises(RuntimeError,match='KIS_AUTHENTICATION_FAILED') as error:
        authenticated_client(mojito.KoreaInvestment,api_key='key',api_secret='secret',acc_no='12345678-01',mock=True)
    assert 'private-secret' not in str(error.value)
    assert error.value.__cause__ is None


def test_progress_watchdog_does_not_confuse_heartbeat_with_progress(tmp_path):
    path=tmp_path/'cycle.json';path.write_text('{}');os.utime(path,(100,100))
    assert progress_stalled(path,launched_at=90,now=2000,timeout=1800)
    assert not progress_stalled(path,launched_at=1990,now=2000,timeout=1800)


def test_eod_requires_an_observed_session_and_is_idempotent(monkeypatch,tmp_path):
    monkeypatch.setattr(wf,'PROJECT_ROOT',tmp_path)
    now=datetime(2026,10,6,15,31,tzinfo=wf.KST)
    assert finish_session(now,'DRY_RUN') is None
    log=tmp_path/'logs/dry_run/operational_health.jsonl';log.parent.mkdir(parents=True)
    log.write_text(json.dumps({'timestamp':'2026-10-06T10:00:00+09:00','mode':'DRY_RUN'})+'\n')
    assert finish_session(now,'DRY_RUN')['already_generated'] is False
    assert finish_session(now,'DRY_RUN')['already_generated'] is True
    report=json.loads((tmp_path/'reports/promotion/dry_run/daily/2026-10-06.json').read_text())
    assert report['performance']=={} and report['promotion_gate']['ready'] is False


def test_workflow_api_is_mode_scoped_and_reports_stalled(monkeypatch,tmp_path):
    from api import main as api
    monkeypatch.setattr(api,'LOG_ROOT',tmp_path)
    path=tmp_path/'system/simulate/cycle.json';path.parent.mkdir(parents=True)
    path.write_text(json.dumps({'mode':'SIMULATE','status':'RUNNING','stage':'PREPARE'}));os.utime(path,(1,1))
    assert api.get_workflow_status('SIMULATE')['status']=='STALLED'
    assert api.get_workflow_status('PAPER')['status']=='NOT_STARTED'


def test_bounded_child_is_terminated_on_timeout(tmp_path):
    import subprocess, sys
    from apps.system.processes import run_bounded
    with pytest.raises(subprocess.TimeoutExpired):
        run_bounded([sys.executable,'-c','import time; time.sleep(60)'],
                    cwd=tmp_path,env=dict(os.environ),timeout=0.2)


def test_supervisor_restarts_failure_but_stops_on_success(monkeypatch,tmp_path):
    from apps.system import supervisor
    monkeypatch.setattr(wf,'PROJECT_ROOT',tmp_path)
    children=[]
    def child(*a,**k):
        code=1 if not children else 0
        children.append(code)
        return SimpleNamespace(poll=lambda:code,wait=lambda:code)
    monkeypatch.setattr(supervisor.subprocess,'Popen',child)
    monkeypatch.setattr(supervisor.time,'sleep',lambda *a:None)
    assert supervisor.supervise(['--mode','dry-run'],mode='dry-run')==0
    assert children==[1,0]
    events=[json.loads(s) for s in (tmp_path/'logs/dry_run/scheduler_supervisor.jsonl').read_text().splitlines()]
    assert any(e['event']=='AUTO_RESTART_SCHEDULED' for e in events)
