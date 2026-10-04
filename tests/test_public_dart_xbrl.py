"""Original filing boundaries: identity, currency, context, time and rollups."""
from datetime import date
import io
import zipfile

import pytest

from data.collectors.public_dart_xbrl import Filing, PublicDartClient, PublicDartError, parse_archive
from apps.worker.analyzer.company_job import build_quarter_fundamentals

FILING = Filing("005930", "00126380", "20250814000001", date(2025, 8, 14), date(2025, 6, 30), "Semi-annual Report (2025.06)")


def archive(*, currency="KRW", entity="00126380", dimension="ConsolidatedMember", residual=0, conflict=False, malformed=False):
    ns='xmlns:i="http://www.xbrl.org/2003/instance" xmlns:ifrs-full="urn:ifrs" xmlns:dart="urn:dart" xmlns:d="http://xbrl.org/2006/xbrldi" xmlns:iso4217="http://www.xbrl.org/2003/iso4217"'
    contexts=[]
    for key,period in [("bs","<i:instant>2025-06-30</i:instant>"),("ytd","<i:startDate>2025-01-01</i:startDate><i:endDate>2025-06-30</i:endDate>"),("q2","<i:startDate>2025-04-01</i:startDate><i:endDate>2025-06-30</i:endDate>")]:
        contexts.append(f'<i:context id="{key}"><i:entity><i:identifier>{entity}</i:identifier><i:segment><d:explicitMember dimension="ifrs-full:ConsolidatedAndSeparateFinancialStatementsAxis">ifrs-full:{dimension}</d:explicitMember></i:segment></i:entity><i:period>{period}</i:period></i:context>')
    facts=[('Assets','bs',1000+residual),('Liabilities','bs',400),('Equity','bs',600),('Revenue','ytd',300),('Revenue','q2',180),('CashFlowsFromUsedInOperatingActivities','ytd',80)]
    if conflict:facts.append(('Revenue','ytd',301))
    xml=f'<i:xbrl {ns}>'+''.join(contexts)+f'<i:unit id="u"><i:measure>iso4217:{currency}</i:measure></i:unit>'
    xml+=''.join(f'<ifrs-full:{name} contextRef="{ctx}" unitRef="u" decimals="0">{value}</ifrs-full:{name}>' for name,ctx,value in facts)+'</i:xbrl>'
    pre='<l:linkbase xmlns:l="http://www.xbrl.org/2003/linkbase" xmlns:x="http://www.w3.org/1999/xlink">'
    for role,names in [('D210000',['Assets','Liabilities','Equity']),('D310000',['Revenue']),('D520000',['CashFlowsFromUsedInOperatingActivities'])]:
        pre+=f'<l:presentationLink x:role="urn:role-{role}">'+''.join(f'<l:loc x:href="t.xsd#ifrs-full_{name}"/>' for name in names)+'</l:presentationLink>'
    pre+='</l:linkbase>'
    raw=io.BytesIO()
    with zipfile.ZipFile(raw,'w') as z:
        z.writestr('entity00126380_2025-06-30.xbrl',xml[:-4] if malformed else xml)
        z.writestr('entity00126380_2025-06-30_pre.xml',pre)
    return raw.getvalue()


def test_native_amounts_and_ytd_are_preserved_with_receipt_availability():
    rows,audit=parse_archive(archive(),FILING)
    revenue=next(r for r in rows if r['account_id']=='ifrs-full_Revenue')
    assert revenue['thstrm_amount']==180
    assert revenue['thstrm_add_amount']==300
    assert revenue['available_date']==date(2025,8,14)
    assert audit['currency']=='KRW' and audit['balance_residual']==0
    assert audit['source']=='DART_PUBLIC_ORIGINAL_XBRL'


@pytest.mark.parametrize('kwargs,reason',[
    ({'currency':'USD'},'BALANCE_MISSING'),({'entity':'99999999'},'BALANCE_MISSING'),
    ({'dimension':'SeparateMember'},'BALANCE_MISSING'),({'residual':10},'IDENTITY_FAILED'),
    ({'conflict':True},'CONFLICTING_DUPLICATE'),({'malformed':True},'INVALID_XML'),
])
def test_untrustworthy_archives_are_rejected(kwargs,reason):
    with pytest.raises(PublicDartError,match=reason):parse_archive(archive(**kwargs),FILING)


def test_archive_entity_and_period_filename_cannot_be_relabelled():
    wrong=Filing('005930','99999999',FILING.receipt,FILING.received,FILING.period_end,FILING.title)
    with pytest.raises(PublicDartError,match='ENTITY_PERIOD_MISMATCH'):parse_archive(archive(),wrong)


def test_zero_cumulative_flow_is_not_replaced_by_a_quarter_hint():
    row=dict(stock_code='005930',source_rcept_no='20250814000001',bsns_year=2025,
             reprt_code='11012',fs_div='CFS',sj_div='IS',account_id='ifrs-full_Revenue',
             account_nm='Revenue',period_end=date(2025,6,30),available_date=date(2025,8,14),
             thstrm_amount=10,thstrm_add_amount=0)
    q1={**row,'source_rcept_no':'20250515000001','reprt_code':'11013',
        'period_end':date(2025,3,31),'available_date':date(2025,5,15),
        'thstrm_amount':100,'thstrm_add_amount':100}
    reports=build_quarter_fundamentals([q1,row])
    assert reports[-1]['revenue']==-100


def test_public_client_never_sends_api_keys(tmp_path,monkeypatch):
    monkeypatch.setenv('DART_API_KEY','must-not-be-transmitted')
    client=PublicDartClient(tmp_path,delay=0)
    calls=[]
    class Response:
        content=b'public response'
        def raise_for_status(self):pass
    def get(url,**kwargs):
        assert url.startswith('https://engopendart.fss.or.kr/')
        assert 'crtfc_key' not in kwargs.get('params',{})
        assert 'must-not-be-transmitted' not in str(kwargs)
        calls.append(kwargs)
        return Response()
    monkeypatch.setattr(client.session,'get',get)
    assert client.request('/test',{'rcpNo':FILING.receipt})==b'public response'
    assert client.request('/test',{'rcpNo':FILING.receipt})==b'public response'
    assert len(calls)==1


def test_operating_profit_mapping_rejects_subtotals_and_accepts_ifrs_financial_profit():
    from apps.worker.analyzer.company_job import _account_row
    other={'sj_div':'IS','account_id':'issuer_subtotal','account_nm':'기타 투자 영업이익'}
    before_loss={'sj_div':'IS','account_id':'issuer_before_loss','account_nm':'신용손실충당금 반영전 영업이익'}
    total={'sj_div':'IS','account_id':'ifrs-full_ProfitLossFromOperatingActivities','account_nm':'영업이익'}
    assert _account_row([other,before_loss],'operating_income') is None
    assert _account_row([other,before_loss,total],'operating_income') is total


def test_ambiguous_issuer_total_labels_are_not_selected():
    from apps.worker.analyzer.company_job import _account_row
    totals=[{'sj_div':'IS','account_id':str(i),'account_nm':'영업이익(손실)'} for i in range(2)]
    assert _account_row(totals,'operating_income') is None


def test_market_cap_millions_are_converted_before_valuation(monkeypatch):
    from apps.worker.analyzer import company_job as j
    from apps.worker.analyzer.config import load_config
    record={'stock_code':'005930','available_date':date(2025,8,14)}
    monkeypatch.setattr(j,'fetch_financial_statements_as_of',lambda *a:[])
    monkeypatch.setattr(j,'build_quarter_fundamentals',lambda *a:[record])
    monkeypatch.setattr(j,'fetch_company_statuses',lambda *a:[{'stock_code':'005930','status_code':'ACTIVE'}])
    monkeypatch.setattr(j,'fetch_wics_companies',lambda *a,**k:[{'stock_code':'005930','base_date':date(2025,8,13),'mkt_val':2000,'industry_code':'G4530'}])
    def metrics(records):
        assert records[0]['market_cap']==2_000_000_000
        assert records[0]['market_data_date']==date(2025,8,13)
        return records
    monkeypatch.setattr(j,'_add_derived_metrics',metrics)
    monkeypatch.setattr(j,'score_quarter_fundamentals',lambda *a:[])
    monkeypatch.setattr(j,'upsert_company_quarter_fa',lambda *a:0)
    assert j.refresh_quarterly_scores(None,date(2025,8,14),load_config())==0


def test_official_label_linkbase_is_preserved():
    raw=io.BytesIO()
    labels='''<l:linkbase xmlns:l="http://www.xbrl.org/2003/linkbase" xmlns:x="http://www.w3.org/1999/xlink"><l:labelLink><l:loc x:label="a" x:href="t.xsd#ifrs-full_Revenue"/><l:label x:label="b" x:role="http://www.xbrl.org/2003/role/label">매출액</l:label><l:labelArc x:from="a" x:to="b"/></l:labelLink></l:linkbase>'''
    with zipfile.ZipFile(io.BytesIO(archive())) as original,zipfile.ZipFile(raw,'w') as target:
        for name in original.namelist():target.writestr(name,original.read(name))
        target.writestr('entity00126380_lab-ko.xml',labels)
    rows,_=parse_archive(raw.getvalue(),FILING)
    assert next(r for r in rows if r['account_id']=='ifrs-full_Revenue')['account_nm']=='매출액'


def test_zero_result_singular_pagination_is_not_a_transport_failure(tmp_path,monkeypatch):
    client=PublicDartClient(tmp_path,delay=0)
    monkeypatch.setattr(client,'request',lambda *a,**k:b'<div>[1/1] [total 0 item]</div>')
    assert client.filings({'stock_code':'005930','corp_code':'00126380'},date(2025,1,1),date(2025,12,31))==[]


def test_later_official_filing_date_is_preserved(tmp_path,monkeypatch):
    client=PublicDartClient(tmp_path,delay=0)
    html=b'''<table><tbody><tr><td>1</td><td><a onclick="openCorpInfo('00126380')">Samsung</a></td><td><a onclick="openXbrlReportViewerElementPop('20250515000001')">Quarterly Report (2025.03)</a></td><td>2025.05.16</td></tr></tbody></table><div>[total 1 item]</div>'''
    monkeypatch.setattr(client,'request',lambda *a,**k:html)
    result=client.filings({'stock_code':'005930','corp_code':'00126380'},date(2025,1,1),date(2025,12,31))
    assert result[0].received==date(2025,5,16)


def test_proxy_502_retry_is_bounded_and_only_success_is_cached(tmp_path,monkeypatch):
    import requests
    from data.collectors import public_dart_xbrl as module
    client=PublicDartClient(tmp_path,delay=0);calls=[]
    monkeypatch.setattr(module.time,'sleep',lambda *a:None)
    def get(*a,**k):
        calls.append(1)
        response=requests.Response();response.status_code=502 if len(calls)==1 else 200
        response._content=b'upstream failure' if response.status_code==502 else b'original public data'
        return response
    monkeypatch.setattr(client.session,'get',get)
    assert client.request('/test')==b'original public data'
    assert len(calls)==2
    assert next(tmp_path.glob('*.bin')).read_bytes()==b'original public data'
