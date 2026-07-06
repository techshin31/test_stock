import pandas as pd
import requests
import time
from bs4 import BeautifulSoup

def fetch_investor_flow(code: str, page: int = 1) -> pd.DataFrame:
    """네이버 금융에서 특정 종목의 외국인/기관 순매매량(수급) 데이터를 수집한다.
    
    Parameters
    ----------
    code : str
        종목코드 6자리
    page : int
        페이지 번호 (1페이지당 약 20일치 데이터)
        
    Returns
    -------
    pd.DataFrame
        ['date', 'close', 'inst_net', 'foreigner_net', 'foreigner_ratio']
    """
    url = f"https://finance.naver.com/item/frgn.naver?code={code}&page={page}"
    headers = {"User-Agent": "Mozilla/5.0"}
    
    try:
        res = requests.get(url, headers=headers, timeout=10)
        res.encoding = 'euc-kr'  # 필수
        # 네이버 금융 표 중 투자자별 매매동향은 3번째(인덱스 2)에 위치하는 경우가 많음
        dfs = pd.read_html(res.text)
        
        target_df = None
        for df in dfs:
            col_str = str(df.columns)
            if "순매매량" in col_str and "보유율" in col_str:
                target_df = df
                break
                
        if target_df is None:
            return pd.DataFrame()
            
        # MultiIndex flatten
        if isinstance(target_df.columns, pd.MultiIndex):
            # 1레벨(기관, 외국인 등)과 2레벨(순매매량, 보유율)을 합침
            cols = []
            for col in target_df.columns:
                if col[0] == col[1]:
                    cols.append(col[0])
                else:
                    cols.append(col[0] + col[1])
            target_df.columns = cols
            
        target_df = target_df.dropna(subset=['날짜'])
        
        result = pd.DataFrame()
        result['date'] = target_df['날짜'].astype(str).str.replace(".", "-", regex=False)
        result['close'] = pd.to_numeric(target_df['종가'].astype(str).str.replace(",", "", regex=False), errors='coerce')
        result['inst_net'] = pd.to_numeric(target_df['기관순매매량'].astype(str).str.replace(",", "", regex=False), errors='coerce')
        result['foreigner_net'] = pd.to_numeric(target_df['외국인순매매량'].astype(str).str.replace(",", "", regex=False), errors='coerce')
        
        # 보유율(%)
        if '외국인보유율' in target_df.columns:
            result['foreigner_ratio'] = pd.to_numeric(target_df['외국인보유율'].astype(str).str.replace("%", "", regex=False), errors='coerce')
        else:
            result['foreigner_ratio'] = 0.0
            
        return result.dropna(subset=['date']).reset_index(drop=True)
        
    except Exception as e:
        print(f"[WARN] {code} 수급 데이터 수집 실패: {e}")
        return pd.DataFrame()

if __name__ == "__main__":
    df = fetch_investor_flow("005930")
    print(df.head())
