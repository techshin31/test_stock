import requests
import pandas as pd

def wics_url(date, wics_code):
    '''
    Parameter
    - date[str] : the date corresponding data (yyyymmdd)
    - wics_code[int] : the wics code corresponding data (use wics_lc or wics_mc)
    
    Return
    - url[str]
    '''
    url ='http://www.wiseindex.com/Index/GetIndexComponets?ceil_yn=0&'\
          'dt=' + date + '&sec_cd=G' + str(wics_code)
    return url

def wics_json(date, wics_code):
    '''
    Parameter
    - date[str] : the date corresponding data (yyyymmdd)
    - wics_code[int] : the wics code corresponding data (use wics_lc or wics_mc)
    
    Return
    - json[dict]
    '''
    
    url = wics_url(date, wics_code)
    response = requests.get(url)
    return response.json()


def wics_df(date, wics_code):
    '''
    Parameter
    - date[str] : the date corresponding data (yyyymmdd)
    - wics_code[int] : the wics code corresponding data (use wics_lc or wics_mc)
    
    Return
    - df[DataFrame]
    '''
    json = wics_json(date, wics_code)
    df = pd.json_normalize(json, record_path=['list'])
    df.rename(
        columns={
            'IDX_CD': '', # WICS 지수코드 
            'ALL_MKT_VAL': '', # 지수 내 모든 종목의 시가총액 합계(백만원)
            'CMP_CD': '', # 종목코드
            'CMP_KOR': '', # 종목명
            'MKT_VAL': '', # 시가총액(백만원)
            'WGT': '', # 해당 지수 내에서 이 종목이 차지하는 비중
            'S_WGT': '', # 해당 지수 내에서 이 종목이 차지하는 비중
            'CAL_WGT': '', # 지수 계산 시 적용하는 가중치 계수
            'SEQ': '', #해당 지수 내에서 종목의 순번(보통 시가총액 순위)
            'TOP60': '', # 특정 그룹(예: 시총 상위 60종목) 내에서의 순위
            'APT_SHR_CNT': '', # 지수 산출에 적용되는 유동 주식 수입니다. 전체 발행 주식 중 대주주 지분 등을 제외하고 실제 시장에서 거래 가능한 주식 수를 의미합니다.
        }, 
        inplace=True)
    return df