from datetime import date
import pytest
from apps.backtester.universe import build_fa_reconstructed_universe

class DB:
    def __init__(self,rows):self.rows=rows
    def fetch_all(self,query,params):
        assert 'LEFT JOIN fa_company_results' in query
        return self.rows

def row(month,stock='005930',status='PASS'):
    return dict(run_id=month,effective_date=date(2025,month,1),cutoff_date=date(2025,month,1).replace(day=1)-__import__('datetime').timedelta(days=1),stock_code=stock,latest_available_date=date(2025,1,1),model_version='model',status_code=status)

def build(rows,**kwargs):
    return build_fa_reconstructed_universe(DB(rows),'risk_neutral',date(2025,6,1),date(2025,8,31),'model',**kwargs)

def test_empty_month_exits_existing_stocks_and_next_month_reenters():
    initial,plans,tickers=build([row(6),row(7,None),row(8,'000660')])
    assert initial==['005930.KS']
    assert plans[0].exits==['005930.KS'] and not plans[0].entries
    assert plans[1].entries==['000660.KS']
    assert tickers=={'005930.KS','000660.KS'}

@pytest.mark.parametrize('change',[{'status_code':'FAIL'},{'status_code':'WARNING'},{'model_version':'wrong'},{'latest_available_date':date(2025,6,2)},{'cutoff_date':date(2025,6,1)}])
def test_failed_warning_wrong_version_or_lookahead_rejected(change):
    with pytest.raises(ValueError):build([{**row(6),**change}])

def test_warning_opt_in_never_accepts_failures():
    assert build([row(6,status='WARNING')],allow_warnings=True)[0]==['005930.KS']
    with pytest.raises(ValueError):build([row(6,status='FAIL')],allow_warnings=True)

def test_cash_only_history_cannot_be_reported_as_fa_performance():
    with pytest.raises(ValueError,match='no selected stocks'):build([row(6,None)])


def test_pipeline_uses_inclusive_end_correct_model_and_rejects_missing_fa_prices(monkeypatch,tmp_path):
    from apps.backtester import pipeline
    from apps.backtester.config import BacktesterConfig
    import pandas as pd
    cfg=BacktesterConfig(strategy_name='fa_ta_momentum',universe_source='fa-published',start_date=date(2025,6,1),end_date=date(2025,6,30),initial_capital=1_000_000,risk_free_rate=.03,universe_size=5,rotation_size=2,rotation_interval_years=2,random_seed=42,output_dir=tmp_path,save_charts=False,fa_model_version='chosen-model')
    monkeypatch.setattr(pipeline,'download_kospi_index',lambda start,end:pd.Series([100.],index=pd.to_datetime(['2025-06-02'])))
    monkeypatch.setattr(pipeline,'build_fa_published_universe',lambda *a:(['005930'],[],{'005930'}))
    def download(tickers,**kwargs):
        assert tickers==['005930.KS']
        assert kwargs['end']=='2025-07-01'
        return {}
    def enrich(db,quotes,end,**kwargs):
        assert kwargs['model_version']=='chosen-model'
        return quotes
    monkeypatch.setattr(pipeline,'download_multiple_stocks',download)
    monkeypatch.setattr(pipeline,'enrich_ohlcv_with_fa',enrich)
    with pytest.raises(ValueError,match='price downloads failed'):pipeline.run_backtest_pipeline(cfg,None)
