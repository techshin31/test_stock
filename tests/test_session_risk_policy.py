from datetime import date, datetime
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.execution import session_guard as guard
from core.execution.strategy_policy import resolve_strategy_policy
from core.execution.trader import LiveTrader
from core.broker.simulation import LocalSimulationBroker
from core.strategy.fa_ta_momentum import FaTaMomentumStrategy


@pytest.mark.parametrize('hour,minute,blocked', [(8,59,True),(9,0,False),(15,19,False),(15,20,True)])
def test_submission_boundary(hour, minute, blocked):
    result=guard.submission_blocker('BUY',now=datetime(2026,10,6,hour,minute,tzinfo=guard.KST))
    assert bool(result)==blocked


def test_controls_are_reloaded_per_order(monkeypatch, tmp_path):
    control=tmp_path/'control.json';monkeypatch.setenv('TRADING_CONTROL_PATH',str(control))
    control.write_text(json.dumps({'entries_paused':True}))
    assert guard.submission_blocker('BUY')=='ENTRIES_PAUSED'
    assert guard.submission_blocker('SELL') is None
    control.write_text(json.dumps({'orders_paused':True}))
    assert guard.submission_blocker('SELL')=='ORDERS_PAUSED'
    control.write_text('{')
    assert guard.submission_blocker('BUY')=='INVALID_TRADING_CONTROL'
    assert guard.submission_blocker('SELL',session=date(2026,10,2))=='ORDER_SESSION_CHANGED'


def test_policy_validation_reproduces_paper_without_changing_real():
    env={'VALIDATION_STRATEGY_POLICY':'paper'}
    paper=resolve_strategy_policy('PAPER',env)
    for mode in ['DRY_RUN','SIMULATE']:
        policy=resolve_strategy_policy(mode,env)
        for field in ['max_position_weight','rebalance_band','stop_loss_pct','trailing_stop_enabled','trailing_stop_pct','code']:
            assert getattr(policy,field)==getattr(paper,field)
    assert resolve_strategy_policy('REAL',env).stop_loss_pct==0.10


def test_failed_preparation_still_runs_risk_cycle(monkeypatch, tmp_path):
    from apps.system import workflow as wf
    monkeypatch.setattr(wf,'PROJECT_ROOT',tmp_path)
    monkeypatch.setattr(wf,'now_kst',lambda:datetime(2026,10,6,10,tzinfo=guard.KST))
    def fail(**kwargs):raise wf.WorkflowBlocked('INPUTS_NOT_READY')
    monkeypatch.setattr(wf,'prepare',fail)
    calls=[]
    monkeypatch.setattr(wf,'run_process',lambda args:(calls.append(args) or 0))
    with pytest.raises(wf.WorkflowBlocked):wf.run_cycle(mode='simulate')
    assert len(calls)==1 and calls[0][-1]=='--risk-only'
    report=json.loads((tmp_path/'logs/system/simulate/cycle.json').read_text())
    assert report['status']=='BLOCKED'
    assert report['risk_management']['status']=='COMPLETED'


def test_risk_only_exits_held_position_without_market_or_fa(monkeypatch, tmp_path):
    broker=LocalSimulationBroker(tmp_path/'account.json',initial_cash=10000)
    broker.set_market_price('005930.KS',100)
    broker.place_market_buy('005930.KS',10,idempotency_key='seed')
    broker.set_market_price('005930.KS',70)
    trader=object.__new__(LiveTrader)
    trader.broker=broker;trader.execution_venue='SIMULATE';trader.strategy_name='aggressive'
    trader.strategy=FaTaMomentumStrategy({});trader.log_dir=tmp_path
    trader.risk_state_path=tmp_path/'risk.json'
    monkeypatch.setattr('core.execution.trader.download_multiple_stocks',lambda *a,**k:pytest.fail('risk depends on quotes'))
    orders=trader.run_risk_batch()
    assert len(orders)==1 and orders[0]['type']=='SELL'
    assert trader.last_data_health['risk_check_coverage']==1
    assert trader._execute_orders(orders)[0]['status']=='FILLED'
    assert broker.get_balance()['positions']=={}


def test_broker_checks_window_after_slow_hash_request(monkeypatch):
    from core.broker.kis_api import KisBroker, BrokerResponseError
    broker=object.__new__(KisBroker)
    broker.key='key';broker.secret='secret';broker.is_mock=True
    broker.broker=SimpleNamespace(base_url='https://example.test',access_token='token',acc_no_prefix='12345678',acc_no_postfix='01')
    broker._rate_limit=lambda:None
    def hash_request(*a,**k):
        monkeypatch.setattr(guard,'now_kst',lambda:datetime(2026,10,6,15,20,tzinfo=guard.KST))
        return SimpleNamespace(json=lambda:{'HASH':'hash'})
    broker._safe_request=hash_request
    monkeypatch.setattr('core.broker.kis_api.requests.post',lambda *a,**k:pytest.fail('order submitted after cutoff'))
    with pytest.raises(BrokerResponseError,match='OUTSIDE_ORDER_WINDOW'):
        broker.place_market_buy('005930.KS',1)
