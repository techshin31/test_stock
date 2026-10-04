# QuantPilot 대시보드

읽기 전용 PAPER 운영·시장·리포트 화면입니다. Node.js 24와 lockfile을 사용합니다.

```bash
cd dashboard
npm ci
npm run dev
```

개발 서버는 `127.0.0.1:3000`에서 실행되며 `/api` 요청을
`127.0.0.1:8000`의 FastAPI로 전달합니다.

각 데이터 요청의 마지막 성공 응답 시각과 갱신 오류를 표시합니다. 실패 시 마지막
응답을 유지하되 최신 요청 실패를 명시합니다. 응답 시각과 실제 시세 관측일은
구분하며, 운영 미시작·상태 데이터 준비 중에는 계좌·성과 수치를 생성하지 않습니다.

```bash
npm run lint
npm run build
npx playwright install chromium
npm test
```

브라우저 검사는 Playwright Chromium과 모의 API 응답으로 실행하며, 테스트용 Vite
서버를 `127.0.0.1:3100`에 자동 실행합니다. 기존 Chromium을 사용하려면
`PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH=/usr/bin/chromium npm test`를 실행하세요.
실제 증권 API 키나 주문 권한은 필요하지 않습니다.
