import { lazy, Suspense, useCallback, useEffect, useMemo, useState } from 'react'
import {
  Activity,
  AlertTriangle,
  ArrowDownRight,
  ArrowUpRight,
  BarChart3,
  BookOpenText,
  CheckCircle2,
  ChevronRight,
  CircleDollarSign,
  Clock3,
  FileText,
  Gauge,
  Menu,
  RefreshCw,
  Server,
  ShieldCheck,
  WalletCards,
  X,
  XCircle,
} from 'lucide-react'

const PerformanceChart = lazy(() => import('./PerformanceChart.jsx'))
const MarkdownReport = lazy(() => import('./MarkdownReport.jsx'))

const MODE = 'PAPER'
const REFRESH_MS = 30_000

const money = new Intl.NumberFormat('ko-KR', {
  style: 'currency',
  currency: 'KRW',
  maximumFractionDigits: 0,
})
const number = new Intl.NumberFormat('ko-KR')

function apiUrl(path) {
  const separator = path.includes('?') ? '&' : '?'
  return `${path}${separator}mode=${MODE}`
}

async function requestJson(path, signal) {
  const response = await fetch(apiUrl(path), { signal })
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}))
    throw new Error(payload.detail || `요청 실패 (${response.status})`)
  }
  return response.json()
}

function formatMoney(value) {
  return Number.isFinite(Number(value)) ? money.format(Number(value)) : '—'
}

function formatPercent(value, { decimal = false } = {}) {
  if (!Number.isFinite(Number(value))) return '—'
  const normalized = decimal ? Number(value) * 100 : Number(value)
  return `${normalized.toFixed(2)}%`
}

function toneForState(state) {
  if (['CURRENT', 'NORMAL', 'SCANNING', 'READY', 'FINAL'].includes(state)) return 'positive'
  if (['GENERATING', 'OBSERVING', 'ORDER_SUPPRESSION', 'DEGRADED_DATA_STALE'].includes(state)) return 'warning'
  if (['OVERDUE', 'MISSING', 'FAILED', 'ERROR', 'BLOCKED'].includes(state)) return 'negative'
  return 'neutral'
}

function StatusChip({ state, children }) {
  const tone = toneForState(state)
  return (
    <span className={`status-chip status-chip--${tone}`}>
      <span className="status-chip__dot" aria-hidden="true" />
      {children || state || '확인 중'}
    </span>
  )
}

function Panel({ title, eyebrow, action, className = '', children }) {
  return (
    <section className={`panel ${className}`}>
      {(title || eyebrow || action) && (
        <div className="panel__header">
          <div>
            {eyebrow && <p className="eyebrow">{eyebrow}</p>}
            {title && <h2>{title}</h2>}
          </div>
          {action}
        </div>
      )}
      {children}
    </section>
  )
}

function MetricCard({ icon: Icon, label, value, detail, tone = 'neutral' }) {
  return (
    <article className="metric-card">
      <div className={`metric-card__icon metric-card__icon--${tone}`}><Icon size={16} /></div>
      <p className="metric-card__label">{label}</p>
      <p className="metric-card__value">{value}</p>
      <p className="metric-card__detail">{detail}</p>
    </article>
  )
}

function ProgressMetric({ label, value }) {
  const numeric = Number(value)
  const percent = Number.isFinite(numeric) ? Math.max(0, Math.min(100, numeric * 100)) : 0
  return (
    <div className="progress-metric">
      <div className="progress-metric__label">
        <span>{label}</span>
        <strong>{Number.isFinite(numeric) ? `${percent.toFixed(1)}%` : '—'}</strong>
      </div>
      <div className="progress-metric__track" aria-hidden="true">
        <span style={{ width: `${percent}%` }} />
      </div>
    </div>
  )
}

function EvidenceProgress({ label, current, required }) {
  const completed = Number(current) || 0
  const target = Math.max(Number(required) || 0, 1)
  const ratio = Math.max(0, Math.min(1, completed / target))
  return (
    <div className={`evidence-progress ${ratio >= 1 ? 'is-complete' : ''}`}>
      <div className="evidence-progress__label">
        <span>{label}</span>
        <strong>{number.format(completed)} / {number.format(target)}</strong>
      </div>
      <div
        className="evidence-progress__track"
        role="progressbar"
        aria-label={label}
        aria-valuemin="0"
        aria-valuemax={target}
        aria-valuenow={completed}
      >
        <span style={{ width: `${ratio * 100}%` }} />
      </div>
    </div>
  )
}

const READINESS_LABELS = {
  execution_stress_robustness: '체결 표본과 스트레스 검증',
  shadow_observation_window: '재진입 shadow 관측',
  paper_operating_window: 'PAPER 완료 세션',
  paper_final_report_window: 'FINAL·READY 일일 보고서',
  latest_final_report: '최신 완료 세션 보고서',
  daily_final_report_coverage: '세션별 보고서 연속성',
  broker_history_audit: '브로커 주문 원장 감사',
  order_result_parity: '5억원 주문결과 패리티',
  market_data_health: '장중 시장데이터 무결성',
  held_position_risk_coverage: '보유종목 위험평가',
  no_unresolved_runtime_orders: '미종결 주문',
  runtime_error_free: '런타임 오류·차단기',
  latest_eod_operational_integrity: '최근 EOD 운영 무결성',
  scheduler_instance_scope: '단일 PAPER 스케줄러 범위',
  scheduler_supervisor_runtime: 'PAPER 스케줄러 무중단 감독',
  scheduler_recovery_self_test: '스케줄러 자동 복구 자기진단',
}

function SystemReadiness({ readiness }) {
  if (!readiness) {
    return (
      <Panel title="자동매매 완성도" className="content-grid__full">
        <div className="empty-inline">아직 생성된 시스템 준비도 감사 결과가 없습니다.</div>
      </Panel>
    )
  }
  const progress = readiness.progress || {}
  const samples = progress.execution_samples || {}
  const shadow = progress.shadow_sessions || {}
  const sessions = progress.paper_sessions || {}
  const reports = progress.final_daily_reports || {}
  const checks = progress.evidence_checks || {}
  const safetyChecks = progress.safety_checks || {}
  const blockers = Array.isArray(readiness.blockers) ? readiness.blockers : []
  const state = readiness.full_system_complete
    ? 'READY'
    : readiness.paper_runtime_safe
      ? 'OBSERVING'
      : 'BLOCKED'
  const blockerDetails = {
    execution_stress_robustness: `BUY ${number.format(samples.buy || 0)}/${number.format(samples.required_per_side || 30)}, SELL ${number.format(samples.sell || 0)}/${number.format(samples.required_per_side || 30)} 표본 필요`,
    shadow_observation_window: `검증 세션 ${number.format(shadow.completed || 0)}/${number.format(shadow.required || 10)}`,
    paper_operating_window: `완료 세션 ${number.format(sessions.completed || 0)}/${number.format(sessions.required || 60)}`,
    paper_final_report_window: `FINAL·READY 보고서 ${number.format(reports.completed || 0)}/${number.format(reports.required || 60)}`,
  }
  const blockerRows = blockers.map((blocker) => {
    const [key, ...detail] = String(blocker).split(':')
    return {
      key,
      label: READINESS_LABELS[key] || key.replaceAll('_', ' '),
      detail: blockerDetails[key] || detail.join(':').trim(),
    }
  })

  return (
    <Panel
      title="자동매매 완성도"
      className="content-grid__full readiness-panel"
      action={<StatusChip state={state}>{state === 'OBSERVING' ? '증거 누적 중' : state}</StatusChip>}
    >
      <div className="readiness-layout">
        <div className="readiness-progress-list">
          <EvidenceProgress label="BUY 체결 표본" current={samples.buy} required={samples.required_per_side} />
          <EvidenceProgress label="SELL 체결 표본" current={samples.sell} required={samples.required_per_side} />
          <EvidenceProgress label="재진입 shadow 세션" current={shadow.completed} required={shadow.required} />
          <EvidenceProgress label="완료 PAPER 세션" current={sessions.completed} required={sessions.required} />
          <EvidenceProgress label="FINAL·READY 보고서" current={reports.completed} required={reports.required} />
        </div>
        <div className="readiness-summary">
          <div className="readiness-summary__headline">
            {readiness.paper_runtime_safe ? <ShieldCheck size={21} /> : <AlertTriangle size={21} />}
            <div>
              <strong>{readiness.paper_runtime_safe ? 'PAPER 런타임은 안전합니다.' : 'PAPER 안전 점검이 필요합니다.'}</strong>
              <span>안전 {number.format(safetyChecks.passed || 0)} / {number.format(safetyChecks.total || 0)} · 증거 {number.format(checks.passed || 0)} / {number.format(checks.total || 0)} 통과</span>
            </div>
          </div>
          {blockerRows.length ? (
            <ul className="readiness-blockers">
              {blockerRows.slice(0, 6).map((item) => (
                <li key={`${item.key}-${item.detail}`}>
                  <span>{item.label}</span>
                  {item.detail ? <small>{item.detail}</small> : null}
                </li>
              ))}
            </ul>
          ) : <p className="readiness-complete">모든 PAPER 증거 게이트를 통과했습니다.</p>}
          <p className="readiness-generated">감사 갱신 {readiness.generated_at || '확인 중'} · REAL 실행 권한 없음</p>
        </div>
      </div>
    </Panel>
  )
}

function LoadingState({ label = '운영 데이터를 불러오는 중입니다.' }) {
  return (
    <div className="state-block" role="status">
      <RefreshCw className="spin" size={24} />
      <p>{label}</p>
    </div>
  )
}

function ErrorState({ message, onRetry }) {
  return (
    <div className="state-block state-block--error" role="alert">
      <AlertTriangle size={26} />
      <div>
        <strong>데이터를 불러오지 못했습니다.</strong>
        <p>{message}</p>
      </div>
      <button className="button button--secondary" type="button" onClick={onRetry}>다시 시도</button>
    </div>
  )
}

function FreshnessBanner({ freshness }) {
  if (!freshness) return null
  const icon = freshness.state === 'CURRENT'
    ? <CheckCircle2 size={20} />
    : freshness.state === 'GENERATING'
      ? <Clock3 size={20} />
      : <XCircle size={20} />
  return (
    <div className={`freshness freshness--${toneForState(freshness.state)}`}>
      {icon}
      <div>
        <div className="freshness__title">
          <strong>공식 리포트 {freshness.state}</strong>
          <span>예상 {freshness.expected_report_date} · 최신 {freshness.latest_report_date || '없음'}</span>
        </div>
        <p>{freshness.message}</p>
      </div>
    </div>
  )
}

function Overview({ overview, onOpenReports }) {
  const dashboard = overview.dashboard || {}
  const report = overview.latest_report || {}
  const operations = report.operations || {}
  const performance = report.performance || {}
  const positions = Array.isArray(dashboard.positions) ? dashboard.positions : []
  const orders = dashboard.actual_orders || dashboard.daily_orders || {}
  const timeline = Array.isArray(dashboard.timeline) ? dashboard.timeline : []
  const health = Array.isArray(overview.health) ? overview.health : []
  const chartData = health.slice(-20).map((row, index) => ({
    index: index + 1,
    freshness: Number(row?.data_health?.fresh_count || 0),
    risk: Number(row?.data_health?.risk_checks_completed || 0),
  }))

  return (
    <>
      <FreshnessBanner freshness={overview.report_freshness} />

      <div className="content-grid readiness-grid">
        <SystemReadiness readiness={overview.system_readiness} />
      </div>

      <div className="metric-grid">
        <MetricCard icon={WalletCards} label="총 평가자산" value={formatMoney(dashboard.total_eval)} detail={`예수금 ${formatMoney(dashboard.cash)}`} />
        <MetricCard icon={dashboard.daily_asset_change >= 0 ? ArrowUpRight : ArrowDownRight} label="당일 자산변동" value={formatMoney(dashboard.daily_asset_change)} detail={formatPercent(dashboard.daily_asset_change_rate)} tone={dashboard.daily_asset_change >= 0 ? 'positive' : 'negative'} />
        <MetricCard icon={CircleDollarSign} label="평가손익" value={formatMoney(dashboard.unrealized_pnl)} detail={`보유 ${number.format(positions.length)}종목`} tone={dashboard.unrealized_pnl >= 0 ? 'positive' : 'negative'} />
        <MetricCard icon={Gauge} label="5억 시작 기준 수익률" value={formatPercent(performance.return_vs_starting_capital, { decimal: true })} detail={`손익 ${formatMoney(performance.pnl_vs_starting_capital)} · 기준선 이후 ${formatPercent(performance.net_return, { decimal: true })}`} tone={performance.return_vs_starting_capital >= 0 ? 'positive' : 'negative'} />
      </div>

      <div className="content-grid">
        <Panel title="보유 포지션" eyebrow="PAPER ACCOUNT" className="content-grid__wide">
          {positions.length ? (
            <div className="table-wrap">
              <table>
                <thead><tr><th>종목</th><th>수량</th><th>평균단가</th><th>현재가</th><th>수익률</th></tr></thead>
                <tbody>
                  {positions.map((position) => (
                    <tr key={position.ticker}>
                      <td><strong>{position.name || position.ticker}</strong><span className="subline">{position.ticker}</span></td>
                      <td>{number.format(position.qty || 0)}</td>
                      <td>{formatMoney(position.avg_price)}</td>
                      <td>{formatMoney(position.current_price)}</td>
                      <td className={Number(position.profit_rate) >= 0 ? 'text-positive' : 'text-negative'}>{formatPercent(position.profit_rate)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : <div className="empty-inline">현재 보유 포지션이 없습니다.</div>}
        </Panel>

        <Panel title="운영 무결성" eyebrow="LATEST OFFICIAL EOD" className="content-grid__side">
          <div className="stack">
            <ProgressMetric label="데이터 신선도" value={operations.data_freshness_rate} />
            <ProgressMetric label="위험점검 커버리지" value={operations.risk_check_coverage} />
            <ProgressMetric label="주문 정산률" value={operations.order_reconciliation_rate} />
          </div>
          <div className="incident-row">
            <span>치명 사고</span>
            <strong className={Number(operations.critical_incidents) > 0 ? 'text-negative' : 'text-positive'}>{operations.critical_incidents ?? '—'}건</strong>
          </div>
        </Panel>

        <Panel title="최근 스캔 흐름" eyebrow="LAST 20 CYCLES" className="content-grid__wide chart-panel">
          {chartData.length ? (
            <Suspense fallback={<LoadingState label="차트를 준비하는 중입니다." />}>
              <PerformanceChart data={chartData} />
            </Suspense>
          ) : <div className="empty-inline">표시할 운영 로그가 없습니다.</div>}
        </Panel>

        <Panel title="오늘 주문" eyebrow="ACTUAL ORDERS" className="content-grid__side">
          <dl className="order-grid">
            <div><dt>매수 체결</dt><dd>{orders.buy_filled || 0}</dd></div>
            <div><dt>매도 체결</dt><dd>{orders.sell_filled || 0}</dd></div>
            <div><dt>정산 대기</dt><dd>{orders.open || 0}</dd></div>
            <div><dt>거절·취소</dt><dd>{orders.rejected || 0}</dd></div>
          </dl>
        </Panel>

        <Panel title="최근 활동" eyebrow="TIMELINE" className="content-grid__wide">
          <ol className="timeline">
            {timeline.length ? timeline.slice().reverse().map((item, index) => (
              <li key={`${item}-${index}`}><span aria-hidden="true" />{item}</li>
            )) : <li className="timeline__empty">기록된 활동이 없습니다.</li>}
          </ol>
        </Panel>

        <Panel
          title={report.date ? `${report.date} 공식 리포트` : '공식 리포트'}
          eyebrow="REPORT STATUS"
          className="content-grid__side"
          action={<StatusChip state={report.report_status}>{report.report_status || '없음'}</StatusChip>}
        >
          <p className="report-summary">{report.executive_summary || '아직 발행된 공식 리포트가 없습니다.'}</p>
          <div className="report-facts">
            <span>검증 <strong>{report.validation_status || '—'}</strong></span>
            <span>차단 조건 <strong>{report.blocker_count ?? '—'}개</strong></span>
          </div>
          <button className="text-button" type="button" onClick={onOpenReports}>전체 리포트 보기 <ChevronRight size={16} /></button>
        </Panel>
      </div>
    </>
  )
}

function Reports({ overview, reports, selectedDate, reportDetail, loading, error, onSelect, onRefresh }) {
  return (
    <>
      <FreshnessBanner freshness={overview?.report_freshness} />
      <div className="reports-layout">
        <Panel
          title="발행 이력"
          eyebrow="OFFICIAL PAPER EOD"
          className="reports-list"
          action={<button className="icon-button" type="button" onClick={onRefresh} aria-label="리포트 새로고침"><RefreshCw size={17} /></button>}
        >
          {loading && !reports.length ? <LoadingState label="리포트 목록을 불러오는 중입니다." /> : null}
          {error ? <ErrorState message={error} onRetry={onRefresh} /> : null}
          {!loading && !error && !reports.length ? <div className="empty-inline">발행된 공식 PAPER 리포트가 없습니다.</div> : null}
          <div className="report-list-items">
            {reports.map((report) => (
              <button
                className={`report-list-item ${selectedDate === report.date ? 'is-active' : ''}`}
                type="button"
                key={report.date}
                onClick={() => onSelect(report.date)}
              >
                <span><strong>{report.date}</strong><small>{report.executive_summary}</small></span>
                <span className="report-list-item__status"><StatusChip state={report.report_status}>{report.report_status}</StatusChip><ChevronRight size={16} /></span>
              </button>
            ))}
          </div>
        </Panel>

        <Panel title={selectedDate ? `${selectedDate} 보고서` : '보고서 상세'} eyebrow="MARKDOWN SOURCE" className="report-reader">
          {loading && !reportDetail ? <LoadingState label="보고서를 불러오는 중입니다." /> : null}
          {!loading && !reportDetail ? <div className="state-block"><BookOpenText size={28} /><p>왼쪽에서 보고서를 선택하세요.</p></div> : null}
          {reportDetail ? (
            <>
              <div className="report-reader__meta">
                <StatusChip state={reportDetail.report?.validation_status}>검증 {reportDetail.report?.validation_status}</StatusChip>
                <span>생성 {reportDetail.report?.generated_at || '—'}</span>
              </div>
              <Suspense fallback={<LoadingState label="보고서를 표시하는 중입니다." />}>
                <MarkdownReport content={reportDetail.content} />
              </Suspense>
            </>
          ) : null}
        </Panel>
      </div>
    </>
  )
}

function App() {
  const [activeTab, setActiveTab] = useState('overview')
  const [overview, setOverview] = useState(null)
  const [overviewError, setOverviewError] = useState('')
  const [overviewLoading, setOverviewLoading] = useState(true)
  const [reports, setReports] = useState([])
  const [reportsError, setReportsError] = useState('')
  const [reportsLoading, setReportsLoading] = useState(false)
  const [selectedDate, setSelectedDate] = useState('')
  const [reportDetail, setReportDetail] = useState(null)

  const loadOverview = useCallback(async (signal) => {
    try {
      setOverviewError('')
      const payload = await requestJson('/api/overview', signal)
      setOverview(payload)
    } catch (error) {
      if (error.name !== 'AbortError') setOverviewError(error.message)
    } finally {
      if (!signal?.aborted) setOverviewLoading(false)
    }
  }, [])

  const selectReport = useCallback(async (date, signal) => {
    setReportDetail(null)
    setReportsLoading(true)
    try {
      setReportsError('')
      setReportDetail(await requestJson(`/api/reports/${encodeURIComponent(date)}`, signal))
    } catch (error) {
      if (error.name !== 'AbortError') setReportsError(error.message)
    } finally {
      if (!signal?.aborted) setReportsLoading(false)
    }
  }, [])

  const loadReports = useCallback(async (signal) => {
    setReportsLoading(true)
    try {
      setReportsError('')
      const payload = await requestJson('/api/reports', signal)
      setReports(payload)
      setSelectedDate((current) => current || payload[0]?.date || '')
    } catch (error) {
      if (error.name !== 'AbortError') setReportsError(error.message)
    } finally {
      if (!signal?.aborted) setReportsLoading(false)
    }
  }, [])

  useEffect(() => {
    const controller = new AbortController()
    loadOverview(controller.signal)
    const interval = window.setInterval(() => loadOverview(controller.signal), REFRESH_MS)
    return () => { controller.abort(); window.clearInterval(interval) }
  }, [loadOverview])

  useEffect(() => {
    if (activeTab !== 'reports') return undefined
    const controller = new AbortController()
    loadReports(controller.signal)
    const interval = window.setInterval(() => loadReports(controller.signal), REFRESH_MS)
    return () => { controller.abort(); window.clearInterval(interval) }
  }, [activeTab, loadReports])

  useEffect(() => {
    if (activeTab !== 'reports' || !selectedDate) return undefined
    const controller = new AbortController()
    selectReport(selectedDate, controller.signal)
    return () => controller.abort()
  }, [activeTab, selectedDate, selectReport])

  const [mobileMenuOpen, setMobileMenuOpen] = useState(false)
  const lastUpdated = useMemo(() => overview?.dashboard?.updated_at || '확인 중', [overview])
  const operationalStatus = overview?.dashboard?.operational_status || 'UNKNOWN'

  return (
    <div className="app-shell">
      {/* Mobile Backdrop & Drawer */}
      {mobileMenuOpen && (
        <div className="mobile-backdrop" onClick={() => setMobileMenuOpen(false)} aria-hidden="true" />
      )}

      <aside className={`sidebar ${mobileMenuOpen ? 'is-mobile-open' : ''}`}>
        <div className="brand">
          <span className="brand__mark"><BarChart3 size={20} /></span>
          <span>QuantPilot<small>Operations</small></span>
          <button className="mobile-close-btn" type="button" onClick={() => setMobileMenuOpen(false)} aria-label="메뉴 닫기">
            <X size={20} />
          </button>
        </div>
        <nav aria-label="주요 메뉴">
          <button
            className={activeTab === 'overview' ? 'is-active' : ''}
            type="button"
            onClick={() => { setActiveTab('overview'); setMobileMenuOpen(false) }}
          >
            <Activity size={18} />운영 현황
          </button>
          <button
            className={activeTab === 'reports' ? 'is-active' : ''}
            type="button"
            onClick={() => { setActiveTab('reports'); setMobileMenuOpen(false) }}
          >
            <FileText size={18} />공식 리포트
          </button>
        </nav>
        <div className="sidebar__footer">
          <div><Server size={16} /><span>읽기 전용 모드</span></div>
          <p>안전 설계로 주문 및 모드 변경은 이 화면에서 차단됩니다.</p>
        </div>
      </aside>

      <main>
        {/* Mobile Navbar Header */}
        <header className="mobile-header">
          <button className="icon-button" type="button" onClick={() => setMobileMenuOpen(true)} aria-label="메뉴 열기">
            <Menu size={22} />
          </button>
          <div className="mobile-brand">
            <BarChart3 size={18} className="text-accent" />
            <span>QuantPilot</span>
          </div>
          <StatusChip state={operationalStatus}>{operationalStatus}</StatusChip>
        </header>

        {/* Topbar */}
        <header className="topbar hero-topbar">
          <div className="hero-topbar__main">
            <div className="hero-topbar__eyebrow">
              <span className="hero-badge">PAPER</span>
              <span className="hero-divider">/</span>
              <span>***9904-01</span>
              <span className="hero-divider">·</span>
              <span>updated {lastUpdated}</span>
            </div>
            <h1>{activeTab === 'overview' ? '운영 현황' : 'EOD 리포트'}</h1>
          </div>
          <div className="topbar__status">
            <StatusChip state={operationalStatus}>{operationalStatus}</StatusChip>
            <span className="mode-badge">PAPER MODE</span>
            <button
              className="icon-button"
              type="button"
              onClick={() => loadOverview()}
              title="새로고침"
            >
              <RefreshCw size={14} />
            </button>
          </div>
        </header>

        <div className="page-content">
          {overviewLoading && !overview ? <LoadingState /> : null}
          {overviewError && !overview ? <ErrorState message={overviewError} onRetry={() => { setOverviewLoading(true); loadOverview() }} /> : null}
          {overview && activeTab === 'overview' ? <Overview overview={overview} onOpenReports={() => setActiveTab('reports')} /> : null}
          {overview && activeTab === 'reports' ? (
            <Reports
              overview={overview}
              reports={reports}
              selectedDate={selectedDate}
              reportDetail={reportDetail}
              loading={reportsLoading}
              error={reportsError}
              onSelect={setSelectedDate}
              onRefresh={() => {
                loadReports()
                if (selectedDate) selectReport(selectedDate)
              }}
            />
          ) : null}
        </div>
      </main>
    </div>
  )
}

export default App
