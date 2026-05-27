# 한국투자증권 Open API

한국투자증권 모의투자 API 연동을 위한 최소 클라이언트입니다. API 키는 코드에 직접 넣지 않고 `api/.env` 또는 시스템 환경변수로 관리합니다.

## 1. 환경변수 준비

`api/.env.example`을 참고해서 `api/.env` 파일을 만듭니다.

```env
KIS_APP_KEY=발급받은_APP_KEY
KIS_APP_SECRET=발급받은_APP_SECRET
KIS_ENV=paper

KIS_DOMESTIC_STOCK_ACCOUNT_NO=국내주식_계좌번호_앞8자리
KIS_DOMESTIC_STOCK_ACCOUNT_PRODUCT_CODE=국내주식_계좌번호_뒤2자리

KIS_DOMESTIC_FUTURES_ACCOUNT_NO=국내선물옵션_계좌번호_앞8자리
KIS_DOMESTIC_FUTURES_ACCOUNT_PRODUCT_CODE=국내선물옵션_계좌번호_뒤2자리
```

`KIS_ENV` 값은 모의투자는 `paper`, 실전은 `real`입니다. 처음에는 반드시 `paper`로 두고 조회 API부터 확인하세요.

## 2. 토큰 발급 확인

프로젝트 루트에서 실행합니다.

```powershell
python -m api.smoke_test token
```

## 3. 모의투자 잔고 조회

```powershell
python -m api.smoke_test balance
```

현재 `balance`는 국내주식 계좌 잔고 조회입니다. 국내선물옵션은 계좌 설정만 먼저 분리해뒀고, 주문/계좌 TR은 다음 단계에서 별도 메서드로 붙일 예정입니다.

## 4. 국내주식 현재가 조회

삼성전자 예시입니다.

```powershell
python -m api.smoke_test price 005930
```

## 참고

- 모의투자 REST URL: `https://openapivts.koreainvestment.com:29443`
- 실전 REST URL: `https://openapi.koreainvestment.com:9443`
- 접근토큰 발급 경로: `/oauth2/tokenP`
