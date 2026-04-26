## 시장 참조데이터 수집

이 폴더는 FA 점수체계에 필요한 시장데이터를 수집하기 위한 스크립트를 담는다.

수집 대상:

- 주가
- 거래량
- 거래대금
- 시가총액
- 상장주식수
- PER
- PBR
- EPS
- BPS
- DIV
- DPS

### 실행 파일

- [fetch_market_reference_data.py](/C:/dev/Service_Stock_Analysis/etl/stock/fetch_market_reference_data.py)

### 출력 파일

- `etl/stock/data/market_reference_snapshot_<YYYYMMDD>.csv`
- `etl/stock/data/market_reference_monthly_<START>_<END>.csv`

### 설치 예시

```powershell
C:\Users\shin\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m pip install -r etl\stock\requirements.txt
```

### 실행 예시

```powershell
C:\Users\shin\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe etl\stock\fetch_market_reference_data.py --date 20260424
```

```powershell
C:\Users\shin\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe etl\stock\fetch_market_reference_data.py --date 20260424 --start-date 20210101 --end-date 20251231
```
