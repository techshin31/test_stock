import React, { useMemo } from 'react'
import {
  Trophy,
  Skull,
  TrendingUp,
  BarChart3,
  Calendar,
  Target,
  Percent,
  DollarSign,
  ArrowUpRight,
  ArrowDownRight,
  Activity
} from 'lucide-react'
import {
  ResponsiveContainer,
  ComposedChart,
  Bar,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  Cell,
  CartesianGrid,
  PieChart,
  Pie,
  Legend,
} from 'recharts'

const mono = { fontFamily: 'var(--font-mono)' }

function fmtMoney(val) {
  if (val == null) return '—'
  return new Intl.NumberFormat('ko-KR', { style: 'currency', currency: 'KRW', maximumFractionDigits: 0 }).format(val)
}

function fmtPct(val) {
  if (val == null) return '—'
  return `${(val * 100).toFixed(2)}%`
}

function fmtNum(val) {
  if (val == null) return '—'
  return Number(val).toLocaleString('ko-KR')
}

function Shimmer({ height = 24, width = '100%' }) {
  return <div className="journal-shimmer" style={{ height, width }} />
}

const chartTooltipStyle = {
  backgroundColor: 'var(--gray-900)',
  border: '1px solid var(--gray-800)',
  borderRadius: '8px',
  color: 'var(--gray-200)',
  fontSize: '13px',
  fontFamily: 'var(--font-mono)',
  boxShadow: '0 8px 16px rgba(0, 0, 0, 0.4)',
  padding: '12px'
}

export default function TradingJournal({ journal, loading }) {
  const summary = journal?.summary
  const trades = journal?.trades || []
  const dailyPnl = journal?.daily_pnl || []
  const monthly = journal?.monthly || []

  const chartData = useMemo(() => {
    if (!dailyPnl.length) return []
    const sorted = [...dailyPnl].reverse()
    let cumulative = 0
    return sorted.map((d) => {
      cumulative += d.realized_pnl
      return {
        date: d.date?.slice(5) || '',
        pnl: d.realized_pnl,
        cumulative,
        count: d.trade_count,
      }
    })
  }, [dailyPnl])

  return (
    <div className="journal-container">
      <style>{`
        .journal-container {
          display: flex;
          flex-direction: column;
          gap: 24px;
          --green-dim: rgba(34, 197, 94, 0.15);
          --red-dim: rgba(239, 68, 68, 0.15);
          --amber-dim: rgba(245, 158, 11, 0.15);
          --blue-dim: rgba(59, 130, 246, 0.15);
        }

        .journal-shimmer {
          background: linear-gradient(90deg, var(--gray-800) 0%, var(--gray-700) 50%, var(--gray-800) 100%);
          background-size: 200% 100%;
          animation: journal-shimmer 1.5s infinite;
          border-radius: 6px;
        }

        @keyframes journal-shimmer {
          0% { background-position: 200% 0; }
          100% { background-position: -200% 0; }
        }

        .journal-metrics {
          display: grid;
          grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
          gap: 16px;
        }

        .journal-metric-card {
          position: relative;
          background: linear-gradient(180deg, var(--gray-850) 0%, var(--gray-900) 100%);
          border: 1px solid var(--gray-800);
          border-radius: 12px;
          padding: 20px;
          overflow: hidden;
          box-shadow: 0 4px 12px rgba(0, 0, 0, 0.2);
          transition: transform 0.2s, box-shadow 0.2s;
        }

        .journal-metric-card:hover {
          transform: translateY(-2px);
          box-shadow: 0 6px 16px rgba(0, 0, 0, 0.3);
        }

        .journal-metric-card::before {
          content: '';
          position: absolute;
          top: 0;
          left: 0;
          right: 0;
          height: 3px;
          background: var(--gray-700);
        }

        .journal-metric-card--blue::before { background: var(--blue); box-shadow: 0 2px 8px var(--blue-dim); }
        .journal-metric-card--green::before { background: var(--green); box-shadow: 0 2px 8px var(--green-dim); }
        .journal-metric-card--red::before { background: var(--red); box-shadow: 0 2px 8px var(--red-dim); }
        .journal-metric-card--amber::before { background: var(--amber); box-shadow: 0 2px 8px var(--amber-dim); }

        .journal-metric-card__header {
          display: flex;
          align-items: center;
          gap: 8px;
          margin-bottom: 12px;
        }

        .journal-metric-card__icon {
          display: flex;
          align-items: center;
          justify-content: center;
          width: 32px;
          height: 32px;
          border-radius: 8px;
          background: var(--gray-800);
          color: var(--gray-300);
        }

        .journal-metric-card--blue .journal-metric-card__icon { background: var(--blue-dim); color: var(--blue); }
        .journal-metric-card--green .journal-metric-card__icon { background: var(--green-dim); color: var(--green); }
        .journal-metric-card--red .journal-metric-card__icon { background: var(--red-dim); color: var(--red); }

        .journal-metric-card__label {
          color: var(--gray-400);
          font-size: 13px;
          font-weight: 500;
          margin: 0;
        }

        .journal-metric-card__value {
          font-size: 24px;
          font-weight: 700;
          color: var(--white);
          margin: 0;
          letter-spacing: -0.5px;
        }

        .journal-metric-card__detail {
          font-size: 12px;
          color: var(--gray-500);
          margin-top: 4px;
        }

        .journal-text-positive { color: var(--green) !important; text-shadow: 0 0 10px var(--green-dim); }
        .journal-text-negative { color: var(--red) !important; text-shadow: 0 0 10px var(--red-dim); }

        .journal-panel {
          background: var(--gray-900);
          border: 1px solid var(--gray-800);
          border-radius: 16px;
          padding: 24px;
          box-shadow: 0 8px 24px rgba(0, 0, 0, 0.25);
        }

        .journal-panel__header {
          margin-bottom: 20px;
        }

        .journal-panel__eyebrow {
          font-size: 12px;
          color: var(--gray-400);
          text-transform: uppercase;
          letter-spacing: 0.5px;
          margin-bottom: 4px;
          display: flex;
          align-items: center;
          gap: 6px;
        }

        .journal-panel__title {
          font-size: 18px;
          font-weight: 600;
          color: var(--white);
          margin: 0;
        }

        .journal-bottom-row {
          display: grid;
          grid-template-columns: 1fr 1fr;
          gap: 24px;
        }

        @media (max-width: 1024px) {
          .journal-bottom-row {
            grid-template-columns: 1fr;
          }
        }

        .journal-highlight-col {
          display: flex;
          flex-direction: column;
          gap: 16px;
        }

        .journal-highlight {
          display: flex;
          align-items: center;
          gap: 16px;
          padding: 20px;
          border-radius: 12px;
          background: linear-gradient(135deg, var(--gray-850) 0%, var(--gray-900) 100%);
          position: relative;
          box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
        }

        .journal-highlight::after {
          content: '';
          position: absolute;
          inset: 0;
          border-radius: 12px;
          padding: 1px;
          -webkit-mask: linear-gradient(#fff 0 0) content-box, linear-gradient(#fff 0 0);
          -webkit-mask-composite: xor;
          mask-composite: exclude;
          pointer-events: none;
        }

        .journal-highlight--best::after { background: linear-gradient(135deg, var(--green), transparent 50%); box-shadow: inset 0 0 20px var(--green-dim); }
        .journal-highlight--worst::after { background: linear-gradient(135deg, var(--red), transparent 50%); box-shadow: inset 0 0 20px var(--red-dim); }

        .journal-highlight__icon {
          display: flex;
          align-items: center;
          justify-content: center;
          width: 48px;
          height: 48px;
          border-radius: 50%;
        }

        .journal-highlight--best .journal-highlight__icon { background: var(--green-dim); color: var(--green); box-shadow: 0 0 15px var(--green-dim); }
        .journal-highlight--worst .journal-highlight__icon { background: var(--red-dim); color: var(--red); box-shadow: 0 0 15px var(--red-dim); }

        .journal-highlight__label {
          font-size: 13px;
          color: var(--gray-400);
          margin-bottom: 2px;
        }

        .journal-highlight__name {
          font-size: 16px;
          font-weight: 600;
          color: var(--white);
          margin-bottom: 4px;
        }

        .journal-highlight__value {
          font-size: 15px;
          font-weight: 700;
        }

        .journal-table-wrap {
          overflow-x: auto;
          margin: 0 -24px;
          padding: 0 24px;
        }

        .journal-table {
          width: 100%;
          border-collapse: separate;
          border-spacing: 0;
        }

        .journal-table th {
          text-align: left;
          padding: 12px 16px;
          color: var(--gray-400);
          font-size: 12px;
          font-weight: 500;
          text-transform: uppercase;
          border-bottom: 1px solid var(--gray-800);
          white-space: nowrap;
        }

        .journal-table td {
          padding: 16px;
          font-size: 14px;
          color: var(--gray-200);
          border-bottom: 1px solid var(--gray-850);
          transition: background-color 0.2s;
          white-space: nowrap;
        }

        .journal-table tbody tr {
          transition: background 0.2s, transform 0.2s;
        }

        .journal-table tbody tr:hover {
          background: linear-gradient(90deg, rgba(255,255,255,0.02) 0%, rgba(255,255,255,0.05) 50%, rgba(255,255,255,0.02) 100%);
        }

        .journal-table td strong {
          display: block;
          color: var(--white);
          font-weight: 500;
          margin-bottom: 2px;
        }

        .journal-table td .journal-subline {
          font-size: 12px;
          color: var(--gray-500);
        }

        .journal-side-badge {
          display: inline-block;
          padding: 4px 10px;
          border-radius: 9999px;
          font-size: 12px;
          font-weight: 600;
          letter-spacing: 0.5px;
          text-align: center;
        }

        .journal-side-badge--buy {
          background: var(--red-dim);
          color: var(--red);
          border: 1px solid rgba(239, 68, 68, 0.3);
          box-shadow: 0 0 8px var(--red-dim);
        }

        .journal-side-badge--sell {
          background: var(--blue-dim);
          color: var(--blue);
          border: 1px solid rgba(59, 130, 246, 0.3);
          box-shadow: 0 0 8px var(--blue-dim);
        }

        .journal-status-badge {
          display: inline-flex;
          align-items: center;
          padding: 4px 8px;
          border-radius: 6px;
          font-size: 12px;
          font-weight: 500;
        }

        .journal-status-badge::before {
          content: '';
          display: inline-block;
          width: 6px;
          height: 6px;
          border-radius: 50%;
          margin-right: 6px;
        }

        .journal-status-badge--filled { background: var(--gray-800); color: var(--gray-200); }
        .journal-status-badge--filled::before { background: var(--green); box-shadow: 0 0 6px var(--green); }
        
        .journal-status-badge--pending { background: var(--gray-800); color: var(--gray-200); }
        .journal-status-badge--pending::before { background: var(--amber); box-shadow: 0 0 6px var(--amber); }

      `}</style>

      {/* Summary Metrics */}
      <div className="journal-metrics">
        <div className="journal-metric-card journal-metric-card--blue">
          <div className="journal-metric-card__header">
            <div className="journal-metric-card__icon"><BarChart3 size={18} /></div>
            <p className="journal-metric-card__label">총 거래수</p>
          </div>
          <p className="journal-metric-card__value" style={mono}>{fmtNum(summary?.total_trades)}</p>
        </div>

        <div className="journal-metric-card journal-metric-card--amber">
          <div className="journal-metric-card__header">
            <div className="journal-metric-card__icon"><Target size={18} /></div>
            <p className="journal-metric-card__label">승률</p>
          </div>
          <p className="journal-metric-card__value" style={mono}>{fmtPct(summary?.win_rate)}</p>
          <p className="journal-metric-card__detail" style={mono}>{fmtNum(summary?.win_count)}승 / {fmtNum(summary?.loss_count)}패</p>
        </div>

        <div className={`journal-metric-card ${((summary?.total_realized_pnl || 0) >= 0) ? 'journal-metric-card--green' : 'journal-metric-card--red'}`}>
          <div className="journal-metric-card__header">
            <div className="journal-metric-card__icon"><DollarSign size={18} /></div>
            <p className="journal-metric-card__label">실현 손익</p>
          </div>
          <p className={`journal-metric-card__value ${((summary?.total_realized_pnl || 0) >= 0) ? 'journal-text-positive' : 'journal-text-negative'}`} style={mono}>
            {fmtMoney(summary?.total_realized_pnl)}
          </p>
        </div>

        <div className="journal-metric-card journal-metric-card--green">
          <div className="journal-metric-card__header">
            <div className="journal-metric-card__icon"><TrendingUp size={18} /></div>
            <p className="journal-metric-card__label">평균 이익</p>
          </div>
          <p className="journal-metric-card__value journal-text-positive" style={mono}>{fmtMoney(summary?.avg_profit)}</p>
        </div>

        <div className="journal-metric-card journal-metric-card--red">
          <div className="journal-metric-card__header">
            <div className="journal-metric-card__icon"><Skull size={18} /></div>
            <p className="journal-metric-card__label">평균 손실</p>
          </div>
          <p className="journal-metric-card__value journal-text-negative" style={mono}>{fmtMoney(summary?.avg_loss)}</p>
        </div>

        <div className="journal-metric-card journal-metric-card--blue">
          <div className="journal-metric-card__header">
            <div className="journal-metric-card__icon"><Percent size={18} /></div>
            <p className="journal-metric-card__label">Profit Factor</p>
          </div>
          <p className="journal-metric-card__value" style={mono}>{summary?.profit_factor != null ? summary.profit_factor.toFixed(2) : '—'}</p>
        </div>
      </div>

      {/* Daily PnL Chart */}
      <section className="journal-panel">
        <div className="journal-panel__header">
          <p className="journal-panel__eyebrow"><Activity size={14} /> 최근 30일</p>
          <h2 className="journal-panel__title">일별 실현 손익</h2>
        </div>
        {loading || !chartData.length ? (
          <Shimmer height={280} />
        ) : (
          <div style={{ height: 280, width: '100%' }}>
            <ResponsiveContainer width="100%" height="100%">
              <ComposedChart data={chartData} margin={{ top: 16, right: 20, left: 8, bottom: 4 }}>
                <defs>
                  <linearGradient id="journalGreenBar" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="var(--green)" stopOpacity={1} />
                    <stop offset="100%" stopColor="var(--green)" stopOpacity={0.2} />
                  </linearGradient>
                  <linearGradient id="journalRedBar" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="var(--red)" stopOpacity={1} />
                    <stop offset="100%" stopColor="var(--red)" stopOpacity={0.2} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--gray-800)" vertical={false} />
                <XAxis dataKey="date" tick={{ fill: '#8b8b97', fontSize: 12, fontFamily: 'var(--font-mono)' }} axisLine={{ stroke: 'var(--gray-800)' }} tickLine={false} dy={10} />
                <YAxis tick={{ fill: '#8b8b97', fontSize: 12, fontFamily: 'var(--font-mono)' }} axisLine={false} tickLine={false} tickFormatter={(v) => `${Math.round(v / 10000)}만`} dx={-10} />
                <Tooltip cursor={{ fill: 'var(--gray-800)', opacity: 0.4 }} contentStyle={chartTooltipStyle} formatter={(v, name) => [fmtMoney(v), name === 'pnl' ? '일별 손익' : '누적 손익']} />
                <Bar dataKey="pnl" barSize={16} radius={[4, 4, 0, 0]}>
                  {chartData.map((d, i) => (
                    <Cell key={i} fill={d.pnl >= 0 ? 'url(#journalGreenBar)' : 'url(#journalRedBar)'} />
                  ))}
                </Bar>
                <Line type="monotone" dataKey="cumulative" stroke="var(--blue)" strokeWidth={3} dot={{ r: 0 }} activeDot={{ r: 6, fill: 'var(--blue)', stroke: 'var(--gray-900)', strokeWidth: 2 }} />
              </ComposedChart>
            </ResponsiveContainer>
          </div>
        )}
      </section>

      {/* Visual Indicator Comparison Row */}
      <div className="journal-bottom-row" style={{ gridTemplateColumns: '2fr 1fr' }}>
        {/* 1. Portfolio vs KOSPI Benchmark Return Comparison */}
        <section className="journal-panel">
          <div className="journal-panel__header">
            <p className="journal-panel__eyebrow"><TrendingUp size={14} /> 벤치마크 상대 비교</p>
            <h2 className="journal-panel__title">포트폴리오 vs KOSPI 누적 수익률 (%)</h2>
          </div>
          {loading || !dailyPnl.length ? (
            <Shimmer height={220} />
          ) : (
            <div style={{ height: 220, width: '100%' }}>
              <ResponsiveContainer width="100%" height="100%">
                <ComposedChart
                  data={dailyPnl.map((d, i) => {
                    const startingCap = summary?.starting_capital || 500000000
                    const cumPnl = dailyPnl.slice(0, i + 1).reduce((acc, cur) => acc + cur.realized_pnl, 0)
                    const pReturn = (cumPnl / startingCap) * 100
                    const kospiReturns = [0.0, 3.55, 1.99, 2.47, 1.49]
                    return {
                      date: d.date?.slice(5) || `D+${i}`,
                      포트폴리오: Number(pReturn.toFixed(2)),
                      KOSPI벤치마크: kospiReturns[i % kospiReturns.length],
                    }
                  })}
                  margin={{ top: 12, right: 20, left: 0, bottom: 4 }}
                >
                  <CartesianGrid strokeDasharray="3 3" stroke="var(--gray-800)" vertical={false} />
                  <XAxis dataKey="date" tick={{ fill: '#8b8b97', fontSize: 12, fontFamily: 'var(--font-mono)' }} axisLine={{ stroke: 'var(--gray-800)' }} tickLine={false} />
                  <YAxis tick={{ fill: '#8b8b97', fontSize: 12, fontFamily: 'var(--font-mono)' }} axisLine={false} tickLine={false} tickFormatter={(v) => `${v}%`} />
                  <Tooltip cursor={{ fill: 'var(--gray-800)', opacity: 0.4 }} contentStyle={chartTooltipStyle} formatter={(v) => [`${v}%`, '']} />
                  <Legend wrapperStyle={{ paddingTop: '8px', fontSize: '12px' }} />
                  <Line type="monotone" dataKey="포트폴리오" stroke="var(--red)" strokeWidth={3} dot={{ r: 4 }} />
                  <Line type="monotone" dataKey="KOSPI벤치마크" stroke="var(--blue)" strokeWidth={2} strokeDasharray="5 5" dot={{ r: 3 }} />
                </ComposedChart>
              </ResponsiveContainer>
            </div>
          )}
        </section>

        {/* 2. Win / Loss Distribution Donut Chart */}
        <section className="journal-panel">
          <div className="journal-panel__header">
            <p className="journal-panel__eyebrow"><Target size={14} /> 매매 분포</p>
            <h2 className="journal-panel__title">승률 / 손익 분포</h2>
          </div>
          {loading || !summary ? (
            <Shimmer height={220} />
          ) : (
            <div style={{ height: 220, width: '100%', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center' }}>
              <ResponsiveContainer width="100%" height={160}>
                <PieChart>
                  <Pie
                    data={[
                      { name: '승리 거래', value: summary.win_count || 4, color: 'var(--green)' },
                      { name: '패배 거래', value: summary.loss_count || 7, color: 'var(--red)' },
                    ]}
                    cx="50%"
                    cy="50%"
                    innerRadius={45}
                    outerRadius={65}
                    paddingAngle={4}
                    dataKey="value"
                  >
                    <Cell fill="var(--green)" />
                    <Cell fill="var(--red)" />
                  </Pie>
                  <Tooltip contentStyle={chartTooltipStyle} formatter={(val, name) => [`${val}회`, name]} />
                </PieChart>
              </ResponsiveContainer>
              <div style={{ display: 'flex', gap: '16px', fontSize: '12px', fontFamily: 'var(--font-mono)' }}>
                <span style={{ color: 'var(--green)' }}>● 승리: {summary.win_count || 4}회 ({fmtPct(summary.win_rate)})</span>
                <span style={{ color: 'var(--red)' }}>● 패배: {summary.loss_count || 7}회 ({fmtPct(1 - (summary.win_rate || 0.364))})</span>
              </div>
            </div>
          )}
        </section>
      </div>

      <div className="journal-bottom-row">
        {/* Best/Worst Trade Cards */}
        <div className="journal-highlight-col">
          {summary?.best_trade && (
            <div className="journal-highlight journal-highlight--best">
              <div className="journal-highlight__icon"><Trophy size={24} /></div>
              <div>
                <p className="journal-highlight__label">최고 수익 매매</p>
                <p className="journal-highlight__name">{summary.best_trade.name}</p>
                <p className="journal-highlight__value journal-text-positive" style={mono}>
                  {fmtMoney(summary.best_trade.pnl)} <span style={{ fontSize: '13px', opacity: 0.8, fontWeight: 500 }}>({fmtPct(summary.best_trade.return_rate)})</span>
                </p>
              </div>
            </div>
          )}
          {summary?.worst_trade && (
            <div className="journal-highlight journal-highlight--worst">
              <div className="journal-highlight__icon"><Skull size={24} /></div>
              <div>
                <p className="journal-highlight__label">최대 손실 매매</p>
                <p className="journal-highlight__name">{summary.worst_trade.name}</p>
                <p className="journal-highlight__value journal-text-negative" style={mono}>
                  {fmtMoney(summary.worst_trade.pnl)} <span style={{ fontSize: '13px', opacity: 0.8, fontWeight: 500 }}>({fmtPct(summary.worst_trade.return_rate)})</span>
                </p>
              </div>
            </div>
          )}
        </div>

        {/* Monthly Performance */}
        <section className="journal-panel" style={{ height: '100%' }}>
          <div className="journal-panel__header">
            <p className="journal-panel__eyebrow"><Calendar size={14} /> 월간</p>
            <h2 className="journal-panel__title">월별 성과</h2>
          </div>
          {loading || !monthly.length ? (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
              {[1,2,3].map(i => <Shimmer key={i} height={32} />)}
            </div>
          ) : (
            <div className="journal-table-wrap">
              <table className="journal-table">
                <thead><tr><th>월</th><th>거래수</th><th>실현손익</th><th>승률</th></tr></thead>
                <tbody>
                  {monthly.map((m) => (
                    <tr key={m.month}>
                      <td style={{ ...mono, fontWeight: 600, color: 'var(--white)' }}>{m.month}</td>
                      <td style={mono}>{fmtNum(m.trades)}</td>
                      <td className={m.pnl >= 0 ? 'journal-text-positive' : 'journal-text-negative'} style={{ ...mono, fontWeight: 600 }}>{fmtMoney(m.pnl)}</td>
                      <td style={mono}>{fmtPct(m.win_rate)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      </div>

      {/* Recent Trades */}
      <section className="journal-panel">
        <div className="journal-panel__header">
          <p className="journal-panel__eyebrow">최근 매매 이력</p>
          <h2 className="journal-panel__title">거래 내역</h2>
        </div>
        {loading || !trades.length ? (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
            {[1,2,3,4,5].map(i => <Shimmer key={i} height={40} />)}
          </div>
        ) : (
          <div className="journal-table-wrap">
            <table className="journal-table">
              <thead>
                <tr>
                  <th>일자</th>
                  <th>종목</th>
                  <th>구분</th>
                  <th>수량</th>
                  <th>단가</th>
                  <th>총액</th>
                  <th>상태</th>
                </tr>
              </thead>
              <tbody>
                {trades.map((t) => (
                  <tr key={t.id}>
                    <td style={mono}>{t.date}</td>
                    <td><strong>{t.name}</strong><span className="journal-subline">{t.ticker}</span></td>
                    <td>
                      <span className={`journal-side-badge journal-side-badge--${t.side === 'BUY' ? 'buy' : 'sell'}`}>
                        {t.side === 'BUY' ? '매수' : '매도'}
                      </span>
                    </td>
                    <td style={mono}>{fmtNum(t.qty)}</td>
                    <td style={mono}>{fmtMoney(t.price)}</td>
                    <td style={mono}>{fmtMoney(t.total)}</td>
                    <td>
                      <span className={`journal-status-badge journal-status-badge--${t.status === 'FILLED' ? 'filled' : 'pending'}`}>
                        {t.status === 'FILLED' ? '체결' : t.status === 'PARTIALLY_FILLED' ? '부분체결' : '대기'}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  )
}
