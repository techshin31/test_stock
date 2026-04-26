## DART 참조데이터 수집

이 폴더는 재무제표 외에 FA 스코어링에 필요한 DART 공시 참조데이터를 수집하기 위한 스크립트를 담는다.

현재 수집 대상:

- 배당 관련 공시
- 자기주식 취득/처분 공시
- 주식 소각 공시
- 유상증자/무상증자 공시
- 전환사채/신주인수권부사채/교환사채 공시
- 임상/허가/기술수출/공급계약 등 이벤트성 공시

### 실행 파일

- [fetch_dart_reference_events.py](/C:/dev/Service_Stock_Analysis/etl/company/fetch_dart_reference_events.py)

### 출력 파일

- `etl/company/data/dart_reference_events_<START>_<END>.csv`

### 설치 예시

```powershell
C:\Users\shin\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m pip install -r etl\company\requirements.txt
```

### 실행 예시

```powershell
$env:DART_API_KEY="YOUR_KEY"
C:\Users\shin\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe etl\company\fetch_dart_reference_events.py --start-date 20210101 --end-date 20260424
```

```powershell
$env:DART_API_KEY="YOUR_KEY"
C:\Users\shin\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe etl\company\fetch_dart_reference_events.py --start-date 20250101 --end-date 20260424 --limit 20
```
