import pandas as pd
import requests
import numpy as np

def fetch_consensus(code: str) -> dict:
    """네이버 금융에서 특정 종목의 기업실적분석(컨센서스) 데이터를 수집한다.
    
    Parameters
    ----------
    code : str
        종목코드 6자리
        
    Returns
    -------
    dict
        {'forward_eps': float, 'forward_per': float, 'op_yoy': float, ...}
    """
    url = f"https://finance.naver.com/item/main.naver?code={code}"
    headers = {"User-Agent": "Mozilla/5.0"}
    
    res = requests.get(url, headers=headers, timeout=10)
    html_text = res.content.decode('euc-kr', 'replace')
    html_text = html_text.replace('euc-kr', 'utf-8')
    dfs = pd.read_html(html_text)
    
    target_df = None
    for df in dfs:
        # 기업실적분석 표는 보통 컬럼이 10개 내외, 행이 15개 이상
        if df.shape[0] >= 15 and df.shape[1] >= 9:
            target_df = df
            break
                
    if target_df is None:
        return {}
        
    # 컬럼 단순화 (날짜 부분만 추출)
    # target_df.columns는 (주요재무정보, 최근 연간 실적, 2023.12, IFRS연결) 형태
    dates = [col[2] for col in target_df.columns]
    target_df.columns = dates
    
    # 인덱스를 항목 이름으로 설정
    target_df.index = target_df.iloc[:, 0].tolist()
    target_df = target_df.drop(target_df.columns[0], axis=1)
    
    # (E)가 붙은 미래 추정치 컬럼 찾기 (최근 분기 또는 최근 연간)
    estimate_cols = [c for c in target_df.columns if "(E)" in str(c)]
    
    result = {}
    
    if estimate_cols:
        best_col = estimate_cols[-1] # 분기 중 가장 먼 미래 추정치
        eps_val = target_df.iloc[9][best_col]
        per_val = target_df.iloc[10][best_col]
        op_val = target_df.iloc[1][best_col]
    else:
        # 없으면 가장 최근 확정치 사용
        best_col = target_df.columns[-1]
        eps_val = target_df.iloc[9][best_col]
        per_val = target_df.iloc[10][best_col]
        op_val = target_df.iloc[1][best_col]
        
    def _parse_val(v):
        if isinstance(v, pd.Series):
            v = v.iloc[0]
        if pd.isnull(v) or v == '-':
            return 0.0
        try:
            return float(str(v).replace(',', ''))
        except:
            return 0.0
            
    result['forward_eps'] = _parse_val(eps_val)
    result['forward_per'] = _parse_val(per_val)
    result['estimated_op'] = _parse_val(op_val)
    
    return result

if __name__ == "__main__":
    print("Samsung:", fetch_consensus("005930"))
