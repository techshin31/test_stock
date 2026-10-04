from contextlib import contextmanager
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

from apps.worker.collector import public_company, public_finance, company_job
from data.collectors.public_dart_events import PublicDartEventsClient, parse_events_page, REPORT_TYPES
from data.collectors.public_dart_xbrl import PublicDartError

START, END = date(2026, 1, 1), date(2026, 6, 30)


def page(receipt='20260615000001', owner='00126380', received='2026.06.15', code='11324', total=1):
    row = f"""<tr><td><span class='tagCom_kospi'>S</span><span onclick="openCorpInfo('{owner}')">Company</span></td><td>{received}</td><td><a onclick="openReportViewerDetail('{receipt}','6','','','{code}')">facts</a></td></tr>"""
    return f'<table><tbody>{row if total else ""}</tbody></table><div>[total {total} items]</div>'.encode()


def test_policy_receipt_keeps_source_identity_and_public_availability():
    records, total = parse_events_page(page(received='2026.06.16'), '11324', START, END)
    assert total == 1 and records[0]['corp_code'] == '00126380'
    assert records[0]['rcept_dt'] == date(2026, 6, 16)
    assert records[0]['event_subtype_code'] == 'CONVERTIBLE_BOND'
    assert 'POLICY_SCOPE_ONLY' in records[0]['rm']


@pytest.mark.parametrize('kwargs', [
    {'owner':'invalid'}, {'receipt':'invalid'}, {'received':'2026.07.01'},
    {'received':'2026.06.14'}, {'code':'11325'},
])
def test_invalid_policy_identity_dates_and_report_type_are_rejected(kwargs):
    with pytest.raises(PublicDartError):parse_events_page(page(**kwargs), '11324', START, END)


def test_http_200_error_page_cannot_be_reported_as_no_risk():
    with pytest.raises(PublicDartError):parse_events_page(b'<html>URL not found</html>','11324',START,END)


def test_empty_policy_results_are_distinct_from_a_broken_page():
    rows,total=parse_events_page(page(total=0),'11324',START,END)
    assert rows==[] and total==0


def test_every_policy_type_must_finish_and_pagination_cannot_skip_rows(tmp_path, monkeypatch):
    client=PublicDartEventsClient(tmp_path,delay=0);calls=[]
    monkeypatch.setenv('DART_API_KEY','not-needed-for-public-source')
    def request(path, params, **kwargs):
        assert 'crtfc_key' not in params
        assert params['bgnDe']=='2026.01.01' and params['corpType']=='P'
        calls.append(params['reportCode']);return page(code=params['reportCode'],total=0)
    monkeypatch.setattr(client,'request',request)
    events,counts=client.events(START,END)
    assert events==[] and set(counts)==set(REPORT_TYPES) and set(calls)==set(REPORT_TYPES)
    monkeypatch.setattr(client,'request',lambda path,params,**k:page(total=2,code=params['reportCode']))
    with pytest.raises(PublicDartError,match='PAGINATION_INCOMPLETE'):client.events(START,END)


class DB:
    def fetch_all(self, query, params=None):
        if 'wics_companies' in query:return [{'stock_code':'005930'}]
        return [{'stock_code':'005930','corp_code':'00126380'}]
    @contextmanager
    def transaction(self):yield self


@pytest.mark.parametrize('financial_status',['PASS','PARTIAL'])
def test_public_job_collects_policy_risks_without_calling_authenticated_api(tmp_path,monkeypatch,financial_status):
    writes=[];risk_queries=[]
    monkeypatch.setattr(public_finance,'run',lambda *a,**k:{'status':financial_status})
    policy_row={'corp_code':'00126380','rcept_no':'20260615000001'}
    monkeypatch.setattr(PublicDartEventsClient,'events',lambda self,start,end:risk_queries.append((start,end)) or ([policy_row,{'corp_code':'not-registered'}],{code:1 for code in REPORT_TYPES}))
    monkeypatch.setattr(public_company,'upsert_dart_events',lambda db,rows:writes.extend(rows))
    monkeypatch.setattr(public_company,'refresh_company_risk_states',lambda *a:1)
    monkeypatch.setattr(public_company,'rebuild_annual_fa_metrics',lambda *a:3)
    result=public_company.run(DB(),start=START,end=END,years=[2026],cache_dir=tmp_path,output=tmp_path/'report.json')
    assert result['status']==financial_status and result['risk_disclosure_coverage']=='POLICY_SCOPE_ONLY'
    assert result['dart_events']==1 and writes[0]['stock_code']=='005930'
    assert (tmp_path/'report.json').exists()
    assert risk_queries==[(START,END)]


def test_partial_risk_download_never_writes_events_or_claims_complete_coverage(tmp_path,monkeypatch):
    monkeypatch.setattr(public_finance,'run',lambda *a,**k:{'status':'PASS'})
    def fail(*a):raise PublicDartError('PUBLIC_DART_TRANSPORT')
    monkeypatch.setattr(PublicDartEventsClient,'events',fail)
    monkeypatch.setattr(public_company,'upsert_dart_events',lambda *a:pytest.fail('Incomplete coverage must not write'))
    with pytest.raises(PublicDartError):public_company.run(DB(),start=START,end=END,years=[2026],cache_dir=tmp_path,output=tmp_path/'report.json')
    import json
    saved=json.loads((tmp_path/'report.json').read_text())
    assert saved['status']=='FAILED' and saved['risk_disclosure_coverage']=='NOT_COLLECTED'


def test_default_company_job_dispatches_public_and_bootstraps_active_risk_lookback(tmp_path,monkeypatch):
    calls=[]
    monkeypatch.setattr(public_company,'run',lambda *a,**kw:calls.append(kw) or {'status':'PASS'})
    assert company_job.run(DB(),years=[2026],dart_start_date='20260629',dart_end_date='20260630',cache_dir=tmp_path)['status']=='PASS'
    assert calls[0]['start']==date(2026,6,29)


def test_worker_partial_collection_has_nonzero_exit_and_closes_database(monkeypatch):
    from apps.worker import __main__ as worker
    db=SimpleNamespace(closed=False);db.close=lambda:setattr(db,'closed',True)
    monkeypatch.setattr(worker,'_init',lambda:(SimpleNamespace(dart_start_date='20260101',company_years=[2026]),db))
    monkeypatch.setattr(company_job,'run',lambda *a,**kw:{'status':'PARTIAL','risk_disclosure_coverage':'POLICY_SCOPE_ONLY'})
    args=SimpleNamespace(target='company',start='2026-01-01',end='2026-06-30',years=[2026],no_progress=True,company_size=['LARGE'],check_readiness=False)
    with pytest.raises(SystemExit) as caught:worker.run_collect(args)
    assert caught.value.code==2 and db.closed


def test_public_finance_preserves_suspension_and_rejects_registry_identity_changes(monkeypatch):
    writes=[]
    monkeypatch.setattr(public_finance,'fetch_all_companies',lambda db:[{'stock_code':'005930','corp_code':'00126380','status_code':'SUSPENDED'}])
    monkeypatch.setattr(public_finance,'upsert_companies',lambda db,rows:writes.extend(rows))
    monkeypatch.setattr(public_finance,'fetch_collected_receipts',lambda *a:{'old-receipt'})
    client=SimpleNamespace(company=lambda code:{'stock_code':code,'corp_code':'00126380','market_type_code':'KOSPI','status_code':'ACTIVE'},filings=lambda *a:[])
    report=public_finance.run(None,client,start=START,end=END,years={2026},stock_codes=['005930'],show_progress=False,allow_no_new_filings=True)
    assert report['status']=='PASS' and writes[0]['status_code']=='SUSPENDED'
    client.company=lambda code:{'stock_code':code,'corp_code':'99999999'}
    with pytest.raises(PublicDartError,match='REGISTRY_IDENTITY'):
        public_finance.run(None,client,start=START,end=END,years={2026},stock_codes=['005930'],show_progress=False)
    assert len(writes)==1


def test_daily_collection_queries_a_full_active_risk_window(tmp_path,monkeypatch):
    windows=[]
    monkeypatch.setattr(public_finance,'run',lambda *a,**k:{'status':'PASS'})
    monkeypatch.setattr(PublicDartEventsClient,'events',lambda self,start,end:windows.append((start,end)) or ([],{code:0 for code in REPORT_TYPES}))
    monkeypatch.setattr(public_company,'upsert_dart_events',lambda *a:0)
    monkeypatch.setattr(public_company,'refresh_company_risk_states',lambda *a:0)
    monkeypatch.setattr(public_company,'rebuild_annual_fa_metrics',lambda *a:0)
    public_company.run(DB(),start=date(2026,6,29),end=END,years=[2026],cache_dir=tmp_path,output=tmp_path/'report.json')
    assert windows==[(date(2026,4,1),END)]


def test_policy_collection_keeps_former_large_members_in_historical_scope(monkeypatch):
    class HistoricalDB(DB):
        def fetch_all(self,query,params=None):
            if 'wics_companies' in query:
                assert 'BETWEEN %s AND %s' in query
                return [{'stock_code':'FORMER'}]
            return [{'stock_code':'FORMER','corp_code':'00126380'}]
    writes=[]
    monkeypatch.setattr(public_company,'upsert_dart_events',lambda db,rows:writes.extend(rows))
    monkeypatch.setattr(public_company,'refresh_company_risk_states',lambda *a:1)
    report=public_company.store_policy_events(HistoricalDB(),[{'corp_code':'00126380','rcept_no':'20260615000001'}],{code:1 for code in REPORT_TYPES},start=START,end=END,sizes=['LARGE'])
    assert writes[0]['stock_code']=='FORMER' and report['dart_events']==1


@pytest.mark.parametrize('source', ['api', 'public'])
def test_removed_source_option_is_rejected_before_database_or_network_access(monkeypatch, source):
    from apps.worker import __main__ as worker
    monkeypatch.setattr('sys.argv', ['worker', 'collect', 'company', '--company-source', source])
    monkeypatch.setattr(worker, '_init', lambda: pytest.fail('Removed options must not initialize services'))
    with pytest.raises(SystemExit) as caught:
        worker.main()
    assert caught.value.code == 2


def test_legacy_source_environment_cannot_select_authenticated_collection(monkeypatch):
    from apps.worker import __main__ as worker
    monkeypatch.setenv('COMPANY_DATA_SOURCE', 'api')
    monkeypatch.setenv('DART_API_KEY', 'unused-legacy-binding')
    monkeypatch.setattr('sys.argv', ['worker', 'collect', 'company', '--years', '2026',
                                     '--start', '2026-06-29', '--end', '2026-06-30', '--no-progress'])
    db = SimpleNamespace(closed=False)
    db.close = lambda: setattr(db, 'closed', True)
    monkeypatch.setattr(worker, '_init', lambda: (SimpleNamespace(dart_start_date='20200101'), db))
    calls = []
    monkeypatch.setattr(public_company, 'run', lambda *a, **kw: calls.append(kw) or {'status': 'PASS'})
    worker.main()
    assert db.closed and len(calls) == 1
    assert calls[0]['start'] == date(2026, 6, 29) and calls[0]['end'] == END


def test_public_transport_failure_exits_nonzero_closes_db_and_reports_sanitized_error(monkeypatch, capsys):
    from apps.worker import __main__ as worker
    db = SimpleNamespace(closed=False)
    db.close = lambda: setattr(db, 'closed', True)
    monkeypatch.setattr(worker, '_init', lambda: (SimpleNamespace(dart_start_date='20260101'), db))
    monkeypatch.setattr('sys.argv', ['worker', 'collect', 'company', '--years', '2026', '--no-progress'])
    def fail(*a, **kw):
        raise PublicDartError('PUBLIC_DART_TRANSPORT: HTTPError: HTTP 502')
    monkeypatch.setattr(public_company, 'run', fail)
    with pytest.raises(SystemExit) as caught:
        worker.main()
    assert caught.value.code == 1 and db.closed
    assert capsys.readouterr().err == '[COLLECT FAILED] PUBLIC_DART_TRANSPORT: HTTPError: HTTP 502\n'
