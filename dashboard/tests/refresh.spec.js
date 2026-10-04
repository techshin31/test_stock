import { expect, test } from '@playwright/test'

const initialOverview = {
  mode: 'PAPER', dashboard: null, health: [], latest_report: null,
  runtime: { state: 'NOT_STARTED', message: '아직 운영 상태가 생성되지 않았습니다.' },
}
const indices = {
  available: true, source: 'TEST', history: [],
  kospi: { price: 2750, change: 10, change_rate: 0.3, as_of_date: '2026-09-30' },
  kosdaq: { price: 850, change: 1, change_rate: 0.1, as_of_date: '2026-09-30' },
}

async function mockApi(page, handler) {
  await page.route('**/api/**', async (route) => {
    const path = new URL(route.request().url()).pathname
    if (handler && await handler(route, path)) return
    const json = path === '/api/overview' ? initialOverview
      : path === '/api/market-indices' ? indices
        : { available: false, message: '관측 데이터 준비 중', items: [] }
    await route.fulfill({ json })
  })
}

function statusRow(page, label) {
  return page.getByRole('region', { name: '데이터 갱신 상태' }).locator('li').filter({ has: page.getByText(label, { exact: true }) })
}

test('fresh environment shows not started without inventing balances', async ({ page }) => {
  const errors = []
  page.on('pageerror', (error) => errors.push(error.message))
  await mockApi(page)
  await page.goto('/')
  await expect(page.getByText('운영 미시작', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: '운영 현황', exact: true }).click()
  await expect(page.getByText('운영 상태가 준비되면 계좌와 성과 정보를 표시합니다.')).toBeVisible()
  await expect(page.getByText('총 자산', { exact: true })).toHaveCount(0)
  expect(errors).toEqual([])
})

test('failed refresh retains payload and success time, recovery clears error', async ({ page }) => {
  let fail = false
  await mockApi(page, async (route, path) => {
    if (path !== '/api/market-indices' || !fail) return false
    await route.fulfill({ status: 503, json: { detail: '시장 데이터 서버 연결 실패' } })
    return true
  })
  await page.goto('/')
  const row = statusRow(page, '시장 지수')
  await expect(row).toContainText('응답 확인')
  await expect(page.getByText('2,750.00', { exact: true }).first()).toBeVisible()
  const success = await row.locator('small').textContent()
  fail = true
  await page.getByTitle('새로고침').click()
  await expect(row).toContainText('갱신 실패 · 이전 응답 유지')
  await expect(row).toContainText('시장 데이터 서버 연결 실패')
  expect(await row.locator('small').textContent()).toBe(success)
  await expect(page.getByText('2,750.00', { exact: true }).first()).toBeVisible()
  fail = false
  await page.getByTitle('새로고침').click()
  await expect(row).toContainText('응답 확인')
  await expect(row).not.toContainText('갱신 실패')
})

test('service failure is distinct from a not-started runtime', async ({ page }) => {
  await mockApi(page, async (route, path) => {
    if (path !== '/api/overview') return false
    await route.fulfill({ status: 500, json: { detail: 'Invalid JSON: dashboard_state.json' } })
    return true
  })
  await page.goto('/')
  await expect(statusRow(page, '운영 상태')).toContainText('데이터 요청 실패')
  await expect(page.getByText('운영 미시작', { exact: true })).toHaveCount(0)
})

test('initial fetch failure has no success timestamp', async ({ page }) => {
  await mockApi(page, async (route, path) => {
    if (path !== '/api/market-indices') return false
    await route.abort('failed')
    return true
  })
  await page.goto('/')
  const row = statusRow(page, '시장 지수')
  await expect(row).toContainText('데이터 요청 실패')
  await expect(row).toContainText('마지막 성공 응답: 없음')
})

test('a stalled request reports a timeout rather than leaving loading forever', async ({ page }) => {
  await page.clock.install()
  await mockApi(page, async (route, path) => {
    if (path !== '/api/market-indices') return false
    // Keep this endpoint pending while the other sources complete.
    return true
  })
  await page.goto('/')
  await expect(statusRow(page, '운영 상태')).toContainText('응답 확인')
  await page.clock.fastForward(16_000)
  await expect(statusRow(page, '시장 지수')).toContainText('응답 대기 시간이 초과되었습니다.')
})

test('automatic refresh updates failure status without discarding cached quotes', async ({ page }) => {
  await page.clock.install()
  let fail = false
  await mockApi(page, async (route, path) => {
    if (path !== '/api/market-indices' || !fail) return false
    await route.fulfill({ status: 503, json: { detail: '자동 갱신 실패' } })
    return true
  })
  await page.goto('/')
  const row = statusRow(page, '시장 지수')
  await expect(row).toContainText('응답 확인')
  const success = await row.locator('small').textContent()
  fail = true
  await page.clock.fastForward(30_000)
  await expect(row).toContainText('자동 갱신 실패')
  expect(await row.locator('small').textContent()).toBe(success)
  await expect(page.getByText('2,750.00', { exact: true }).first()).toBeVisible()
})

test('runtime with activity but no snapshot shows data preparation', async ({ page }) => {
  await mockApi(page, async (route, path) => {
    if (path !== '/api/overview') return false
    await route.fulfill({ json: {
      ...initialOverview,
      health: [{ status: 'STARTING' }],
      runtime: { state: 'DATA_PENDING', message: '운영 기록은 있으나 상태 데이터가 아직 준비되지 않았습니다.' },
    } })
    return true
  })
  await page.goto('/')
  await expect(page.getByText('운영 데이터 준비 중', { exact: true })).toBeVisible()
  await expect(page.getByText('운영 미시작', { exact: true })).toHaveCount(0)
})
