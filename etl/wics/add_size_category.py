import pandas as pd
import glob
import os
import warnings

# 경고 무시 (일부 MKT_VAL 데이터 변환 시 발생하는 경고 방지)
warnings.filterwarnings('ignore')

def get_size_category(rank):
    """KRX 기준 시가총액 순위에 따른 대/중/소형주 분류"""
    if pd.isna(rank):
        return None
    if rank <= 100:
        return '대형주'
    elif rank <= 300:
        return '중형주'
    else:
        return '소형주'

def process_and_save():
    # 처리할 파일 목록 가져오기 (zip, csv 모두)
    files = sorted(glob.glob('./data/csv/wics_company_*.zip') + glob.glob('./data/csv/wics_company_*.csv'))
    
    # "wics_company_" 형식이 아닌 wics.csv, wi26.csv 등은 제외할 경우 필터링
    files = [f for f in files if "wics_company_" in os.path.basename(f)]

    # 중복 파일(예: zip과 csv가 같이 있는 경우 csv만 또는 zip만)을 방지하기 위해 파일 이름을 기준으로 한 번 더 필터링 가능
    # 여기서는 고유한 파일들만 순환
    files = list(set(files))
    
    print(f"총 {len(files)}개의 데이터 파일을 변환합니다...")
    
    for f in files:
        print(f"[{os.path.basename(f)}] 데이터 읽는 중...")
        
        # 파일 확장자에 따른 읽기 방식 차이 지정
        if f.endswith('.zip'):
            df = pd.read_csv(f)
        else:
            df = pd.read_csv(f, encoding='utf-8')
            
        # 1. 시가총액(MKT_VAL) 컬럼 전처리 (문자열에 포함된 콤마(,) 제거 후 숫자로 강제 변환) 
        if df['MKT_VAL'].dtype == 'O':
            df['MKT_VAL_NUM'] = pd.to_numeric(df['MKT_VAL'].astype(str).str.replace(',', ''), errors='coerce')
        else:
            df['MKT_VAL_NUM'] = df['MKT_VAL']
            
        # 2. 거래일자(DATE)별로 그룹화하여 시가총액 기준 등수 매기기 (동점자는 먼저 나온 순서 기준)
        print(f"[{os.path.basename(f)}] 시가총액 순위 및 대/중/소형주 라벨링 중...")
        df['SIZE_RANK'] = df.groupby('DATE')['MKT_VAL_NUM'].rank(method='first', ascending=False)
        
        # 3. 등수 기반으로 'SIZE_CATEGORY' 파생변수 생성
        df['SIZE_CATEGORY'] = df['SIZE_RANK'].apply(get_size_category)
        
        # 4. 연산용 임시 컬럼 삭제
        df.drop(columns=['MKT_VAL_NUM', 'SIZE_RANK'], inplace=True, errors='ignore')
        
        # 5. 기존 파일명(경로)으로 덮어쓰기 (저장)
        print(f"[{os.path.basename(f)}] 저장 중...")
        if f.endswith('.zip'):
            # zip 파일의 내부 압축 파일명 추출 (ex: wics_company_2026.csv)
            archive_name = os.path.basename(f).replace('.zip', '.csv')
            # zip 포맷으로 묶어서 저장
            df.to_csv(f, index=False, encoding='utf-8-sig', compression={"method": "zip", "archive_name": archive_name})
        else:
            df.to_csv(f, index=False, encoding='utf-8-sig')
            
        print(f"[{os.path.basename(f)}] 완료!\n")

    print("모든 파일의 변환 및 저장이 완료되었습니다!")

if __name__ == "__main__":
    process_and_save()
