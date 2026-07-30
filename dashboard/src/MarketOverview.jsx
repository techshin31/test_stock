import React, { useMemo } from 'react'
import {
  TrendingUp,
  TrendingDown,
  Minus,
  Activity,
  Globe,
  BarChart3,
  Layers,
} from 'lucide-react'
import {
  ResponsiveContainer,
  BarChart,
  Bar,
  LabelList,
  AreaChart,
  Area,
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  Legend,
  CartesianGrid,
} from 'recharts'
import {
  CHART_COLORS,
  chartAxisLine,
  chartAxisTick,
  chartCursor,
  chartGrid,
  chartLegendStyle,
  chartTooltipStyle,
  formatShortDate,
} from './chartTheme'

const mono = { fontFamily: 'var(--font-mono)' }

function fmt(v, d = 2) {
  if (v == null) return '—'
  return Number(v).toLocaleString('ko-KR', { minimumFractionDigits: d, maximumFractionDigits: d })
}

function fmtPct(v) {
  if (v == null) return '—'
  return `${v > 0 ? '+' : ''}${Number(v).toFixed(2)}%`
}

function fmtVolume(v) {
  if (!v) return '0'
  if (v >= 1_000_000_000_000) return `${(v / 1_000_000_000_000).toFixed(1)}조`
  if (v >= 100_000_000) return `${Math.floor(v / 100_000_000)}억`
  return Number(v).toLocaleString('ko-KR')
}

function DirIcon({ val, size = 18 }) {
  if (!val) return <Minus size={size} />
  return val > 0 ? <TrendingUp size={size} /> : <TrendingDown size={size} />
}

function toneClass(val) {
  if (!val) return 'market-text-muted'
  return val > 0 ? 'market-text-positive' : 'market-text-negative'
}

const REGIME_MAP = {
  UPTREND: { label: '상승장', tone: 'positive' },
  DOWNTREND: { label: '하락장', tone: 'negative' },
  SIDEWAYS: { label: '횡보장', tone: 'warning' },
  TRANSITION: { label: '전환기', tone: 'accent' },
}

function Shimmer({ height = 24, width = '100%' }) {
  return <div className="market-shimmer" style={{ height, width }} />
}

function EmptyData({ message }) {
  return <div className="market-empty" role="status">{message}</div>
}

function fmtVolatility(value) {
  return value == null ? '—' : `${Number(value).toFixed(1)}%`
}

function MarketTrend({ label, history, color, volatility, value }) {
  const points = Array.isArray(history) ? history : []
  const hasHistory = points.length >= 2
  const firstDate = points[0]?.date
  const lastDate = points.at(-1)?.date
  const gradientId = `market-trend-fill-${label.replace(/[^A-Za-z0-9]/g, '-')}`

  return (
    <section className="market-trend" aria-label={`${label} 60거래일 추이와 변동성`}>
      <div className="market-trend__header">
        <div>
          <p className="market-trend__label">{label}</p>
          <strong className="market-trend__value" style={mono}>{fmt(value)}</strong>
        </div>
        <div className="market-trend__volatility" title="최근 20개 일간 수익률의 연환산 표준편차입니다.">
          <span>20일 실현 변동성</span>
          <strong style={mono}>{fmtVolatility(volatility)}</strong>
        </div>
      </div>
      {hasHistory ? (
        <div className="market-trend__chart" role="img" aria-label={`${label} 종가 추이: ${firstDate}부터 ${lastDate}까지`}>
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={points} margin={{ top: 8, right: 2, left: 2, bottom: 0 }}>
              <defs>
                <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor={color} stopOpacity={0.32} />
                  <stop offset="100%" stopColor={color} stopOpacity={0.02} />
                </linearGradient>
              </defs>
              <XAxis
                dataKey="date"
                axisLine={chartAxisLine}
                tickLine={false}
                tick={chartAxisTick}
                ticks={[firstDate, lastDate]}
                tickFormatter={formatShortDate}
              />
              <YAxis hide domain={['auto', 'auto']} />
              <Tooltip
                contentStyle={chartTooltipStyle}
                cursor={chartCursor}
                labelStyle={{ color: 'var(--gray-300)', marginBottom: 4 }}
                formatter={(close) => [fmt(close), '종가']}
              />
              <Area
                type="monotone"
                dataKey="close"
                stroke={color}
                strokeWidth={2}
                fill={`url(#${gradientId})`}
                isAnimationActive={false}
              />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      ) : (
        <EmptyData message={`${label} 추이 데이터가 아직 충분하지 않습니다.`} />
      )}
      {hasHistory && <p className="market-trend__caption">종가 기준 {firstDate} — {lastDate}</p>}
    </section>
  )
}

const styles = `
.market-overview {
  display: flex;
  flex-direction: column;
  gap: 24px;
  color: var(--gray-100);
  font-family: var(--font-sans);
}

.market-text-positive { color: var(--green); }
.market-text-negative { color: var(--red); }
.market-text-warning { color: var(--amber); }
.market-text-accent { color: var(--blue); }
.market-text-muted { color: var(--gray-400); }

.market-panel {
  background: var(--gray-900);
  border: 1px solid var(--gray-800);
  border-radius: 12px;
  padding: 24px;
  transition: border-color 160ms ease-out;
}
.market-source-note {
  margin: -8px 0 0;
  color: var(--gray-400);
  font-size: 12px;
}
.market-empty {
  min-height: 84px;
  display: grid;
  place-items: center;
  padding: 16px;
  border: 1px dashed var(--gray-700);
  border-radius: 6px;
  color: var(--gray-400);
  font-size: 13px;
  text-align: center;
}
.market-panel:hover {
  border-color: var(--gray-700);
}

.market-regime {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 20px 24px;
  position: relative;
  overflow: hidden;
}

.market-regime--positive { --glow-color: var(--green); --glow-shadow: rgba(34, 197, 94, 0.4); }
.market-regime--negative { --glow-color: var(--red); --glow-shadow: rgba(239, 68, 68, 0.4); }
.market-regime--warning { --glow-color: var(--amber); --glow-shadow: rgba(245, 158, 11, 0.4); }
.market-regime--accent { --glow-color: var(--blue); --glow-shadow: rgba(59, 130, 246, 0.4); }

.market-regime__left {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 16px;
  font-weight: 600;
  color: var(--gray-100);
  position: relative;
  z-index: 1;
}

.market-regime__right {
  display: flex;
  align-items: center;
  gap: 16px;
  position: relative;
  z-index: 1;
}

.market-regime__badge {
  padding: 5px 8px;
  border-radius: 6px;
  font-weight: 600;
  font-size: 13px;
  color: var(--gray-100);
  background: var(--gray-850);
  border: 1px solid var(--glow-color);
}

.market-regime__confidence {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.market-regime__confidence-label {
  font-size: 11px;
  color: var(--gray-400);
  text-transform: uppercase;
  letter-spacing: 0.5px;
}
.market-regime__confidence-track {
  width: 100px;
  height: 4px;
  background: var(--gray-800);
  border-radius: 2px;
  overflow: hidden;
}
.market-regime__confidence-track span {
  display: block;
  height: 100%;
  background: var(--glow-color);
  border-radius: 2px;
  transition: width 1s cubic-bezier(0.4, 0, 0.2, 1);
}
.market-regime__confidence-value {
  font-size: 11px;
  color: var(--gray-300);
  text-align: right;
}

.market-regime__signal {
  font-size: 13px;
  color: var(--gray-300);
  background: var(--gray-850);
  padding: 4px 10px;
  border-radius: 6px;
  border: 1px solid var(--gray-800);
}
.market-regime__signal strong {
  color: var(--gray-100);
}

.market-indices-row {
  display: flex;
  gap: 20px;
}
@media (max-width: 1024px) {
  .market-indices-row {
    flex-direction: column;
  }
}

.market-index-card {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.market-index-card__header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  color: var(--gray-300);
  font-size: 14px;
  font-weight: 500;
}

.market-index-card__body {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.market-index-card__price {
  font-size: 32px;
  font-weight: 700;
  color: var(--white);
  letter-spacing: -0.5px;
  line-height: 1;
}

.market-index-card__change {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 15px;
  font-weight: 600;
}

.market-trends-panel { padding: 20px 24px 16px; }
.market-trends-panel__header {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
}
.market-trends-panel__header h2 {
  margin: 0;
  color: var(--gray-100);
  font-size: 14px;
  font-weight: 650;
}
.market-trends-panel__header p {
  margin: 0;
  color: var(--gray-500);
  font-size: 11px;
  font-family: var(--font-mono);
}
.market-trends-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
}
.market-trend {
  min-width: 0;
  padding: 14px 18px 8px;
}
.market-trend + .market-trend { border-left: 1px solid var(--gray-800); }
.market-trend__header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 10px;
}
.market-trend__label {
  margin: 0 0 3px;
  color: var(--gray-400);
  font-size: 12px;
  font-weight: 650;
}
.market-trend__value {
  color: var(--gray-100);
  font-size: 18px;
  line-height: 1.2;
  letter-spacing: -0.02em;
}
.market-trend__volatility {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 2px;
  color: var(--gray-500);
  font-size: 10px;
  white-space: nowrap;
}
.market-trend__volatility strong { color: var(--gray-300); font-size: 12px; }
.market-trend__chart { height: 130px; margin-top: 10px; }
.market-trend__caption {
  margin: 4px 0 0;
  color: var(--gray-500);
  font-size: 10px;
  font-family: var(--font-mono);
}
@media (max-width: 860px) {
  .market-trends-grid { grid-template-columns: 1fr; }
  .market-trend { padding: 16px 0; }
  .market-trend + .market-trend { border-left: 0; border-top: 1px solid var(--gray-800); }
}

.market-breadth {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.market-breadth__header {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 16px;
  font-weight: 600;
}

.market-breadth__legend {
  display: flex;
  gap: 24px;
  font-size: 13px;
  color: var(--gray-300);
}
.market-breadth__legend span {
  display: flex;
  align-items: center;
  gap: 8px;
}

.market-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  box-shadow: 0 0 8px currentColor;
}
.market-dot--green { color: var(--green); background: var(--green); }
.market-dot--amber { color: var(--amber); background: var(--amber); }
.market-dot--red { color: var(--red); background: var(--red); }

.market-breadth__bar {
  height: 10px;
  border-radius: 5px;
  display: flex;
  overflow: hidden;
  background: var(--gray-850);
  border: 1px solid var(--gray-800);
}

.market-breadth__bar span {
  height: 100%;
  transition: width 160ms ease-out;
}
.market-breadth__bar--adv { background: var(--green); }
.market-breadth__bar--unch { background: var(--amber); }
.market-breadth__bar--dec { background: var(--red); }

.market-breadth__stats {
  display: flex;
  justify-content: space-between;
  font-size: 13px;
  color: var(--gray-400);
}

.market-sectors-row {
  display: flex;
  gap: 20px;
}
@media (max-width: 1024px) {
  .market-sectors-row {
    flex-direction: column;
  }
}

.market-sector-panel {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.market-sector-header p.eyebrow {
  font-size: 12px;
  text-transform: uppercase;
  letter-spacing: 1px;
  color: var(--gray-400);
  margin: 0 0 4px 0;
  font-weight: 600;
}
.market-sector-header h2 {
  font-size: 16px;
  font-weight: 600;
  margin: 0;
  color: var(--gray-100);
}

.market-sector-chart {
  margin-top: 8px;
}

@keyframes shimmer {
  0% { background-position: -1000px 0; }
  100% { background-position: 1000px 0; }
}
.market-shimmer {
  background: linear-gradient(90deg, var(--gray-850) 25%, var(--gray-800) 50%, var(--gray-850) 75%);
  background-size: 1000px 100%;
  animation: shimmer 2s infinite linear;
  border-radius: 6px;
}
`

export default function MarketOverview({ indices, breadth, sectors, exchangeRate, regime, loading }) {
  const regimeInfo = REGIME_MAP[regime?.current] || REGIME_MAP.TRANSITION
  const totalBreadth = breadth?.total || 1
  const hasRegimeConfidence = regime?.confidence != null && Number.isFinite(Number(regime.confidence))
  const isPaperUniverseBreadth = breadth?.source === 'YFINANCE_PAPER_UNIVERSE'
  const sourceNote = [indices, breadth, sectors, exchangeRate, regime]
    .filter((item) => item?.available !== false && item?.source)
    .map((item) => item.source)
    .filter((value, index, values) => values.indexOf(value) === index)
    .join(' · ')

  const indexComparison = useMemo(() => {
    const points = Array.isArray(indices?.history) ? indices.history : []
    const baseline = points[0]
    const kospiBase = Number(baseline?.KOSPI)
    const kosdaqBase = Number(baseline?.KOSDAQ)
    if (!Number.isFinite(kospiBase) || kospiBase <= 0 || !Number.isFinite(kosdaqBase) || kosdaqBase <= 0) {
      return []
    }
    return points.flatMap((point) => {
      const kospi = Number(point?.KOSPI)
      const kosdaq = Number(point?.KOSDAQ)
      if (!Number.isFinite(kospi) || !Number.isFinite(kosdaq)) return []
      return [{
        date: point.date,
        kospi_relative: Number(((kospi / kospiBase) * 100).toFixed(2)),
        kosdaq_relative: Number(((kosdaq / kosdaqBase) * 100).toFixed(2)),
      }]
    })
  }, [indices])

  return (
    <>
      <style>{styles}</style>
      <div className="market-overview">
        {!loading && sourceNote && <p className="market-source-note">데이터 출처: {sourceNote}</p>}
        {/* 1. Market Regime Banner */}
        <div className={`market-panel market-regime market-regime--${regimeInfo.tone}`}>
          <div className="market-regime__left">
            <Activity size={20} />
            <span>시장 국면 모델</span>
          </div>
          {loading ? (
            <div className="market-regime__right">
              <Shimmer height={32} width={100} />
              <Shimmer height={12} width={200} />
            </div>
          ) : regime?.available === false || !regime?.current ? (
            <EmptyData message={regime?.message || '시장 국면 분석 데이터가 없습니다.'} />
          ) : (
            <div className="market-regime__right">
              <span className="market-regime__badge">
                {regimeInfo.label}
              </span>
              {hasRegimeConfidence && (
                <div className="market-regime__confidence">
                  <span className="market-regime__confidence-label">신뢰도</span>
                  <div className="market-regime__confidence-track">
                    <span style={{ width: `${Math.round(regime.confidence * 100)}%` }} />
                  </div>
                  <span className="market-regime__confidence-value" style={mono}>
                    {Math.round(regime.confidence * 100)}%
                  </span>
                </div>
              )}
              {regime.signal && (
                <span className="market-regime__signal" style={mono}>
                  시그널: <strong>{regime.signal}</strong>
                </span>
              )}
            </div>
          )}
        </div>

        {/* 2. Index Cards Row */}
        <div className="market-indices-row">
          {/* KOSPI */}
          <div className="market-panel market-index-card">
            <div className="market-index-card__header">
              <span>코스피 (KOSPI)</span>
              <Layers size={18} />
            </div>
            {loading ? (
              <div className="market-index-card__body">
                <Shimmer height={40} width="70%" />
                <Shimmer height={20} width="50%" />
              </div>
            ) : indices?.available === false || !indices?.kospi ? (
              <EmptyData message={indices?.message || 'KOSPI 데이터를 불러올 수 없습니다.'} />
            ) : (
              <div className="market-index-card__body">
                <div className="market-index-card__price" style={mono}>{fmt(indices.kospi.price)}</div>
                <div className={`market-index-card__change ${toneClass(indices.kospi.change)}`} style={mono}>
                  <DirIcon val={indices.kospi.change} />
                  <span>{fmt(Math.abs(indices.kospi.change || 0))}</span>
                  <span>({fmtPct(indices.kospi.change_rate)})</span>
                </div>
              </div>
            )}
          </div>

          {/* KOSDAQ */}
          <div className="market-panel market-index-card">
            <div className="market-index-card__header">
              <span>코스닥 (KOSDAQ)</span>
              <Layers size={18} />
            </div>
            {loading ? (
              <div className="market-index-card__body">
                <Shimmer height={40} width="70%" />
                <Shimmer height={20} width="50%" />
              </div>
            ) : indices?.available === false || !indices?.kosdaq ? (
              <EmptyData message={indices?.message || 'KOSDAQ 데이터를 불러올 수 없습니다.'} />
            ) : (
              <div className="market-index-card__body">
                <div className="market-index-card__price" style={mono}>{fmt(indices.kosdaq.price)}</div>
                <div className={`market-index-card__change ${toneClass(indices.kosdaq.change)}`} style={mono}>
                  <DirIcon val={indices.kosdaq.change} />
                  <span>{fmt(Math.abs(indices.kosdaq.change || 0))}</span>
                  <span>({fmtPct(indices.kosdaq.change_rate)})</span>
                </div>
              </div>
            )}
          </div>

          {/* Exchange Rate */}
          <div className="market-panel market-index-card">
            <div className="market-index-card__header">
              <span>환율 (USD/KRW)</span>
              <Globe size={18} />
            </div>
            {loading ? (
              <div className="market-index-card__body">
                <Shimmer height={40} width="70%" />
                <Shimmer height={20} width="50%" />
              </div>
            ) : exchangeRate?.available === false || !exchangeRate?.usd_krw ? (
              <EmptyData message={exchangeRate?.message || 'USD/KRW 데이터를 불러올 수 없습니다.'} />
            ) : (
              <div className="market-index-card__body">
                <div className="market-index-card__price" style={mono}>{fmt(exchangeRate.usd_krw)}</div>
                <div className={`market-index-card__change ${toneClass(exchangeRate.change)}`} style={mono}>
                  <DirIcon val={exchangeRate.change} />
                  <span>{fmt(Math.abs(exchangeRate.change || 0))}</span>
                  <span>({fmtPct(exchangeRate.change_rate)})</span>
                </div>
              </div>
            )}
          </div>
        </div>

        {/* 2.5 Index Trend Comparison Line Chart */}
        <div className="market-panel">
          <div className="market-breadth__header" style={{ marginBottom: '16px' }}>
            <TrendingUp size={20} />
            <span>KOSPI vs KOSDAQ 상대 추이 · 기준값 100</span>
          </div>
          {loading ? (
            <Shimmer height={200} />
          ) : !indexComparison.length ? (
            <EmptyData message="지수 추이 이력은 아직 수집되지 않았습니다." />
          ) : (
            <div style={{ height: 200, width: '100%' }}>
              <ResponsiveContainer width="100%" height="100%">
                <LineChart
                  data={indexComparison}
                  margin={{ top: 12, right: 16, left: 4, bottom: 0 }}
                >
                  <CartesianGrid {...chartGrid} />
                  <XAxis dataKey="date" tick={chartAxisTick} axisLine={chartAxisLine} tickLine={false} tickFormatter={formatShortDate} minTickGap={28} />
                  <YAxis domain={['auto', 'auto']} tick={chartAxisTick} axisLine={chartAxisLine} tickLine={false} tickFormatter={(value) => value.toFixed(0)} width={34} />
                  <Tooltip cursor={chartCursor} contentStyle={chartTooltipStyle} formatter={(value) => [`${Number(value).toFixed(2)}`, '기준값']} />
                  <Legend wrapperStyle={chartLegendStyle} />
                  <Line name="KOSPI" type="monotone" dataKey="kospi_relative" stroke={CHART_COLORS.accent} strokeWidth={2.5} dot={false} activeDot={{ r: 4, fill: CHART_COLORS.accent, stroke: 'var(--gray-900)', strokeWidth: 2 }} isAnimationActive={false} />
                  <Line name="KOSDAQ" type="monotone" dataKey="kosdaq_relative" stroke={CHART_COLORS.positive} strokeWidth={2.5} dot={false} activeDot={{ r: 4, fill: CHART_COLORS.positive, stroke: 'var(--gray-900)', strokeWidth: 2 }} isAnimationActive={false} />
                </LineChart>
              </ResponsiveContainer>
            </div>
          )}
        </div>

        {/* 3. Separate market trends and realised volatility */}
        <section className="market-panel market-trends-panel" aria-labelledby="market-trends-heading">
          <div className="market-trends-panel__header">
            <h2 id="market-trends-heading">시장 추이와 변동성</h2>
            <p>60거래일 종가 · 20일 실현 변동성</p>
          </div>
          {loading ? (
            <Shimmer height={180} />
          ) : (
            <div className="market-trends-grid">
              <MarketTrend
                label="KOSPI"
                history={indices?.series?.kospi}
                color="var(--blue)"
                volatility={indices?.volatility?.kospi_20d}
                value={indices?.kospi?.price}
              />
              <MarketTrend
                label="KOSDAQ"
                history={indices?.series?.kosdaq}
                color="var(--green)"
                volatility={indices?.volatility?.kosdaq_20d}
                value={indices?.kosdaq?.price}
              />
              <MarketTrend
                label="USD/KRW"
                history={exchangeRate?.history}
                color="var(--amber)"
                volatility={exchangeRate?.volatility_20d}
                value={exchangeRate?.usd_krw}
              />
            </div>
          )}
        </section>

        {/* 4. Market Breadth */}
        <div className="market-panel market-breadth">
          <div className="market-breadth__header">
            <BarChart3 size={20} />
            <span>{isPaperUniverseBreadth ? 'PAPER 유니버스 등락 비율' : '시장 등락 비율 (Market Breadth)'}</span>
          </div>
          {loading ? (
            <div className="market-breadth__shimmer" style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
              <Shimmer height={14} width="100%" />
              <Shimmer height={12} width="40%" />
            </div>
          ) : breadth?.available === false || !breadth ? (
            <EmptyData message={breadth?.message || '시장 등락 비율 데이터가 없습니다.'} />
          ) : (
            <>
              <div className="market-breadth__legend" style={mono}>
                <span><span className="market-dot market-dot--green" /> 상승 {breadth.advancing}</span>
                <span><span className="market-dot market-dot--amber" /> 보합 {breadth.unchanged}</span>
                <span><span className="market-dot market-dot--red" /> 하락 {breadth.declining}</span>
              </div>
              <div className="market-breadth__bar">
                <span className="market-breadth__bar--adv" style={{ width: `${(breadth.advancing / totalBreadth) * 100}%` }} />
                <span className="market-breadth__bar--unch" style={{ width: `${(breadth.unchanged / totalBreadth) * 100}%` }} />
                <span className="market-breadth__bar--dec" style={{ width: `${(breadth.declining / totalBreadth) * 100}%` }} />
              </div>
              <div className="market-breadth__stats" style={mono}>
                <span>상승 비율: {fmt(breadth.advance_ratio * 100)}%</span>
                {breadth.universe_size && <span>커버리지: {breadth.coverage}/{breadth.universe_size}</span>}
                {breadth.trading_volume != null && <span>거래량 합계: {fmtVolume(breadth.trading_volume)}</span>}
              </div>
            </>
          )}
        </div>

        {/* 4. Top / Bottom Sectors */}
        <div className="market-sectors-row">
          <div className="market-panel market-sector-panel">
            <div className="market-sector-header">
              <p className="eyebrow market-text-positive">강세</p>
              <h2>상위 섹터 (Top 5)</h2>
            </div>
            {loading || !sectors?.top?.length ? (
              <div className="market-sector-chart" style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
                {[1,2,3,4,5].map(i => <Shimmer key={i} height={24} />)}
              </div>
            ) : (
              <div className="market-sector-chart">
                <ResponsiveContainer width="100%" height={240}>
                  <BarChart data={sectors.top} layout="vertical" margin={{ top: 0, right: 30, left: 0, bottom: 0 }}>
                    <XAxis type="number" tick={chartAxisTick} axisLine={chartAxisLine} tickLine={false} tickFormatter={(value) => `${value}%`} />
                    <YAxis dataKey="name" type="category" axisLine={false} tickLine={false} tick={{ ...chartAxisTick, fontFamily: 'var(--font-sans)' }} width={112} />
                    <Tooltip cursor={chartCursor} contentStyle={chartTooltipStyle} formatter={(val) => [`+${Number(val).toFixed(2)}%`, '등락률']} />
                    <Bar dataKey="change_rate" fill={CHART_COLORS.positive} radius={[0, 4, 4, 0]} barSize={16} isAnimationActive={false}>
                      <LabelList dataKey="change_rate" position="right" fill={CHART_COLORS.text} fontSize={11} formatter={(value) => `${Number(value) > 0 ? '+' : ''}${Number(value).toFixed(2)}%`} />
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>
            )}
          </div>

          <div className="market-panel market-sector-panel">
            <div className="market-sector-header">
              <p className="eyebrow market-text-negative">약세</p>
              <h2>하위 섹터 (Bottom 5)</h2>
            </div>
            {loading || !sectors?.bottom?.length ? (
              <div className="market-sector-chart" style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
                {[1,2,3,4,5].map(i => <Shimmer key={i} height={24} />)}
              </div>
            ) : (
              <div className="market-sector-chart">
                <ResponsiveContainer width="100%" height={240}>
                  <BarChart data={sectors.bottom.map(s => ({ ...s, abs_rate: Math.abs(s.change_rate) }))} layout="vertical" margin={{ top: 0, right: 30, left: 0, bottom: 0 }}>
                    <XAxis type="number" tick={chartAxisTick} axisLine={chartAxisLine} tickLine={false} tickFormatter={(value) => `${value}%`} />
                    <YAxis dataKey="name" type="category" axisLine={false} tickLine={false} tick={{ ...chartAxisTick, fontFamily: 'var(--font-sans)' }} width={112} />
                    <Tooltip cursor={chartCursor} contentStyle={chartTooltipStyle} formatter={(val, _name, props) => [`${Number(props.payload.change_rate).toFixed(2)}%`, '등락률']} />
                    <Bar dataKey="abs_rate" fill={CHART_COLORS.negative} radius={[0, 4, 4, 0]} barSize={16} isAnimationActive={false}>
                      <LabelList dataKey="change_rate" position="right" fill={CHART_COLORS.text} fontSize={11} formatter={(value) => `${Number(value).toFixed(2)}%`} />
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>
            )}
          </div>
        </div>
      </div>
    </>
  )
}
