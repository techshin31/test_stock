import React from 'react'
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
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  Cell,
  Legend,
  CartesianGrid,
} from 'recharts'

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

const chartTooltipStyle = {
  backgroundColor: 'rgba(17, 17, 19, 0.9)',
  border: '1px solid var(--gray-800)',
  borderRadius: '8px',
  color: 'var(--gray-200)',
  fontSize: '13px',
  fontFamily: 'var(--font-mono)',
  boxShadow: '0 8px 30px rgba(0,0,0,0.5)',
  backdropFilter: 'blur(8px)',
  padding: '10px 14px'
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
  background: linear-gradient(145deg, var(--gray-900) 0%, var(--gray-850) 100%);
  border: 1px solid var(--gray-800);
  border-radius: 16px;
  padding: 24px;
  box-shadow: 0 4px 20px rgba(0, 0, 0, 0.2);
  transition: transform 0.3s cubic-bezier(0.4, 0, 0.2, 1), box-shadow 0.3s cubic-bezier(0.4, 0, 0.2, 1), border-color 0.3s;
}
.market-panel:hover {
  transform: translateY(-2px);
  box-shadow: 0 8px 30px rgba(0, 0, 0, 0.4);
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

.market-regime::before {
  content: '';
  position: absolute;
  top: 0; left: 0; right: 0; bottom: 0;
  background: radial-gradient(circle at 100% 50%, var(--glow-color), transparent 60%);
  opacity: 0.15;
  pointer-events: none;
}

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

@keyframes market-pulse-glow {
  0% { box-shadow: 0 0 0 0 var(--glow-shadow); }
  70% { box-shadow: 0 0 0 10px transparent; }
  100% { box-shadow: 0 0 0 0 transparent; }
}

.market-regime__badge {
  padding: 6px 14px;
  border-radius: 20px;
  font-weight: 600;
  font-size: 14px;
  color: var(--white);
  animation: market-pulse-glow 2s infinite cubic-bezier(0.4, 0, 0.2, 1);
  background: var(--glow-shadow);
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
  border-left-width: 4px;
  border-left-style: solid;
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
  height: 14px;
  border-radius: 7px;
  display: flex;
  overflow: hidden;
  background: var(--gray-850);
  box-shadow: inset 0 2px 6px rgba(0,0,0,0.4);
  border: 1px solid var(--gray-800);
}

.market-breadth__bar span {
  height: 100%;
  transition: width 1s cubic-bezier(0.4, 0, 0.2, 1);
  box-shadow: inset 0 1px 1px rgba(255,255,255,0.15);
}
.market-breadth__bar--adv { background: linear-gradient(180deg, #4ade80, var(--green)); }
.market-breadth__bar--unch { background: linear-gradient(180deg, #fbbf24, var(--amber)); }
.market-breadth__bar--dec { background: linear-gradient(180deg, #f87171, var(--red)); }

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

  return (
    <>
      <style>{styles}</style>
      <div className="market-overview">
        {/* 1. Market Regime Banner */}
        <div className={`market-panel market-regime market-regime--${regimeInfo.tone}`}>
          <div className="market-regime__left">
            <Activity size={20} />
            <span>시장 국면 모델</span>
          </div>
          {loading || !regime ? (
            <div className="market-regime__right">
              <Shimmer height={32} width={100} />
              <Shimmer height={12} width={200} />
            </div>
          ) : (
            <div className="market-regime__right">
              <span className="market-regime__badge">
                {regimeInfo.label}
              </span>
              <div className="market-regime__confidence">
                <span className="market-regime__confidence-label">신뢰도</span>
                <div className="market-regime__confidence-track">
                  <span style={{ width: `${Math.round((regime.confidence || 0) * 100)}%` }} />
                </div>
                <span className="market-regime__confidence-value" style={mono}>
                  {Math.round((regime.confidence || 0) * 100)}%
                </span>
              </div>
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
          <div className="market-panel market-index-card" style={{ borderLeftColor: indices?.kospi?.change > 0 ? 'var(--green)' : indices?.kospi?.change < 0 ? 'var(--red)' : 'var(--gray-600)' }}>
            <div className="market-index-card__header">
              <span>코스피 (KOSPI)</span>
              <Layers size={18} />
            </div>
            {loading || !indices?.kospi ? (
              <div className="market-index-card__body">
                <Shimmer height={40} width="70%" />
                <Shimmer height={20} width="50%" />
              </div>
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
          <div className="market-panel market-index-card" style={{ borderLeftColor: indices?.kosdaq?.change > 0 ? 'var(--green)' : indices?.kosdaq?.change < 0 ? 'var(--red)' : 'var(--gray-600)' }}>
            <div className="market-index-card__header">
              <span>코스닥 (KOSDAQ)</span>
              <Layers size={18} />
            </div>
            {loading || !indices?.kosdaq ? (
              <div className="market-index-card__body">
                <Shimmer height={40} width="70%" />
                <Shimmer height={20} width="50%" />
              </div>
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
          <div className="market-panel market-index-card" style={{ borderLeftColor: exchangeRate?.change > 0 ? 'var(--green)' : exchangeRate?.change < 0 ? 'var(--red)' : 'var(--gray-600)' }}>
            <div className="market-index-card__header">
              <span>환율 (USD/KRW)</span>
              <Globe size={18} />
            </div>
            {loading || !exchangeRate?.usd_krw ? (
              <div className="market-index-card__body">
                <Shimmer height={40} width="70%" />
                <Shimmer height={20} width="50%" />
              </div>
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
            <span>KOSPI vs KOSDAQ 지수 추이 비교</span>
          </div>
          {loading || !indices?.kospi ? (
            <Shimmer height={200} />
          ) : (
            <div style={{ height: 200, width: '100%' }}>
              <ResponsiveContainer width="100%" height="100%">
                <LineChart
                  data={[
                    { date: '07-20', KOSPI: 7096.89, KOSDAQ: 790.28 },
                    { date: '07-21', KOSPI: 7120.45, KOSDAQ: 782.10 },
                    { date: '07-22', KOSPI: 6980.12, KOSDAQ: 775.40 },
                    { date: '07-23', KOSPI: 7096.89, KOSDAQ: 790.28 },
                    { date: '07-24', KOSPI: indices?.kospi?.price || 6690.62, KOSDAQ: indices?.kosdaq?.price || 748.22 },
                  ]}
                  margin={{ top: 10, right: 30, left: 10, bottom: 0 }}
                >
                  <CartesianGrid strokeDasharray="3 3" stroke="var(--gray-800)" vertical={false} />
                  <XAxis dataKey="date" tick={{ fill: '#8b8b97', fontSize: 12, fontFamily: 'var(--font-mono)' }} axisLine={{ stroke: 'var(--gray-800)' }} />
                  <YAxis yAxisId="left" orientation="left" domain={['auto', 'auto']} tick={{ fill: 'var(--blue)', fontSize: 12, fontFamily: 'var(--font-mono)' }} axisLine={false} />
                  <YAxis yAxisId="right" orientation="right" domain={['auto', 'auto']} tick={{ fill: 'var(--green)', fontSize: 12, fontFamily: 'var(--font-mono)' }} axisLine={false} />
                  <Tooltip contentStyle={chartTooltipStyle} />
                  <Legend wrapperStyle={{ paddingTop: '6px', fontSize: '12px' }} />
                  <Line yAxisId="left" type="monotone" dataKey="KOSPI" stroke="var(--blue)" strokeWidth={3} dot={{ r: 4 }} />
                  <Line yAxisId="right" type="monotone" dataKey="KOSDAQ" stroke="var(--green)" strokeWidth={3} dot={{ r: 4 }} />
                </LineChart>
              </ResponsiveContainer>
            </div>
          )}
        </div>

        {/* 3. Market Breadth */}
        <div className="market-panel market-breadth">
          <div className="market-breadth__header">
            <BarChart3 size={20} />
            <span>시장 등락 비율 (Market Breadth)</span>
          </div>
          {loading || !breadth ? (
            <div className="market-breadth__shimmer" style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
              <Shimmer height={14} width="100%" />
              <Shimmer height={12} width="40%" />
            </div>
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
                <span>ADR: {fmt(breadth.advance_ratio * 100)}%</span>
                <span>총 거래대금: ₩{fmtVolume(breadth.trading_volume)}</span>
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
                    <defs>
                      <linearGradient id="market-grad-green" x1="0" y1="0" x2="1" y2="0">
                        <stop offset="0%" stopColor="var(--green)" stopOpacity={1} />
                        <stop offset="100%" stopColor="var(--green)" stopOpacity={0.6} />
                      </linearGradient>
                    </defs>
                    <XAxis type="number" hide />
                    <YAxis dataKey="name" type="category" axisLine={false} tickLine={false} tick={{ fill: 'var(--gray-300)', fontSize: 13, fontFamily: 'var(--font-sans)', fontWeight: 500 }} width={90} />
                    <Tooltip cursor={{ fill: 'var(--gray-800)', opacity: 0.5 }} contentStyle={chartTooltipStyle} formatter={(val) => [`+${val}%`, '등락률']} />
                    <Bar dataKey="change_rate" radius={[0, 6, 6, 0]} barSize={18}>
                      {sectors.top.map((_, i) => <Cell key={i} fill="url(#market-grad-green)" />)}
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
                    <defs>
                      <linearGradient id="market-grad-red" x1="0" y1="0" x2="1" y2="0">
                        <stop offset="0%" stopColor="var(--red)" stopOpacity={1} />
                        <stop offset="100%" stopColor="var(--red)" stopOpacity={0.6} />
                      </linearGradient>
                    </defs>
                    <XAxis type="number" hide />
                    <YAxis dataKey="name" type="category" axisLine={false} tickLine={false} tick={{ fill: 'var(--gray-300)', fontSize: 13, fontFamily: 'var(--font-sans)', fontWeight: 500 }} width={90} />
                    <Tooltip cursor={{ fill: 'var(--gray-800)', opacity: 0.5 }} contentStyle={chartTooltipStyle} formatter={(val, _name, props) => [`${props.payload.change_rate}%`, '등락률']} />
                    <Bar dataKey="abs_rate" radius={[0, 6, 6, 0]} barSize={18}>
                      {sectors.bottom.map((_, i) => <Cell key={i} fill="url(#market-grad-red)" />)}
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
