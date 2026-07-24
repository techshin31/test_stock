import React, { useMemo, useState, useEffect, useRef } from 'react'
import { Layers, TrendingUp, TrendingDown, Flame, Snowflake } from 'lucide-react'
import {
  ResponsiveContainer,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  Cell,
  CartesianGrid,
} from 'recharts'

const mono = { fontFamily: 'var(--font-mono)' }

function fmtRate(rate) {
  if (rate == null) return '—'
  return `${rate > 0 ? '+' : ''}${rate.toFixed(2)}%`
}

function fmtVolume(vol) {
  if (!vol) return '0'
  if (vol >= 1_000_000_000_000) return `${(vol / 1_000_000_000_000).toFixed(1)}조`
  if (vol >= 100_000_000) return `${Math.floor(vol / 100_000_000)}억`
  return Number(vol).toLocaleString('ko-KR')
}

function getGradientStyle(rate) {
  if (rate >= 3) return { background: 'linear-gradient(135deg, rgba(34, 197, 94, 0.4) 0%, rgba(34, 197, 94, 0.1) 100%)', borderColor: 'rgba(34, 197, 94, 0.3)' }
  if (rate >= 1) return { background: 'linear-gradient(135deg, rgba(34, 197, 94, 0.25) 0%, rgba(34, 197, 94, 0.05) 100%)', borderColor: 'rgba(34, 197, 94, 0.2)' }
  if (rate > 0) return { background: 'linear-gradient(135deg, rgba(34, 197, 94, 0.15) 0%, transparent 100%)', borderColor: 'rgba(34, 197, 94, 0.1)' }
  if (rate <= -3) return { background: 'linear-gradient(135deg, rgba(239, 68, 68, 0.4) 0%, rgba(239, 68, 68, 0.1) 100%)', borderColor: 'rgba(239, 68, 68, 0.3)' }
  if (rate <= -1) return { background: 'linear-gradient(135deg, rgba(239, 68, 68, 0.25) 0%, rgba(239, 68, 68, 0.05) 100%)', borderColor: 'rgba(239, 68, 68, 0.2)' }
  if (rate < 0) return { background: 'linear-gradient(135deg, rgba(239, 68, 68, 0.15) 0%, transparent 100%)', borderColor: 'rgba(239, 68, 68, 0.1)' }
  return { background: 'linear-gradient(135deg, var(--gray-800) 0%, var(--gray-850) 100%)', borderColor: 'var(--gray-700)' }
}

function heatmapTextColor(rate) {
  if (rate > 0) return 'var(--green)'
  if (rate < 0) return 'var(--red)'
  return 'var(--gray-400)'
}

function useAnimatedNumber(targetValue, duration = 1200) {
  const [val, setVal] = useState(0)
  const valRef = useRef(0)

  useEffect(() => {
    if (targetValue == null) return
    let startTime
    const startVal = valRef.current
    
    const animate = (timestamp) => {
      if (!startTime) startTime = timestamp
      const progress = Math.min((timestamp - startTime) / duration, 1)
      const easeOutQuart = 1 - Math.pow(1 - progress, 4)
      const current = startVal + (targetValue - startVal) * easeOutQuart
      
      setVal(current)
      
      if (progress < 1) {
        requestAnimationFrame(animate)
      } else {
        setVal(targetValue)
        valRef.current = targetValue
      }
    }
    requestAnimationFrame(animate)
  }, [targetValue, duration])

  return val
}

function AnimatedRate({ value }) {
  const animatedValue = useAnimatedNumber(value)
  if (value == null) return <span className="sector-rate-text">—</span>
  
  return (
    <span 
      className="sector-rate-text"
      style={{ color: heatmapTextColor(value), ...mono }}
    >
      {fmtRate(animatedValue)}
    </span>
  )
}

function SectorShimmer({ height = 24, width = '100%' }) {
  return <div className="sector-shimmer" style={{ height, width }} />
}

const chartTooltipStyle = {
  backgroundColor: 'var(--gray-900)',
  border: '1px solid var(--gray-800)',
  borderRadius: '6px',
  color: 'var(--gray-200)',
  fontSize: '12px',
  fontFamily: 'var(--font-mono)',
  boxShadow: '0 4px 12px rgba(0,0,0,0.5)',
}

export default function SectorAnalysis({ sectors, loading }) {
  const items = sectors?.items || []
  const top5 = useMemo(() => items.slice(0, 5), [items])
  const bottom5 = useMemo(() => [...items].reverse().slice(0, 5), [items])
  const chartData = useMemo(
    () => items.map((s) => ({ name: s.name, change_rate: s.change_rate })),
    [items],
  )

  return (
    <div className="sector-container">
      <style>{`
        .sector-container {
          display: flex;
          flex-direction: column;
          gap: 24px;
        }

        .sector-panel {
          background-color: var(--gray-900);
          border: 1px solid var(--gray-800);
          border-radius: 12px;
          padding: 24px;
          position: relative;
          overflow: hidden;
          box-shadow: 0 4px 20px rgba(0,0,0,0.2);
        }

        .sector-header-wrapper {
          margin-bottom: 24px;
          display: flex;
          justify-content: space-between;
          align-items: flex-end;
        }

        .sector-eyebrow {
          color: var(--gray-400);
          font-size: 13px;
          text-transform: uppercase;
          margin-bottom: 6px;
          display: flex;
          align-items: center;
          gap: 6px;
          letter-spacing: 0.05em;
        }

        .sector-title {
          color: var(--white);
          font-size: 20px;
          font-weight: 600;
          margin: 0;
          position: relative;
          display: inline-block;
          padding-bottom: 4px;
        }

        .sector-title::after {
          content: '';
          position: absolute;
          left: 0;
          bottom: 0;
          width: 40px;
          height: 3px;
          background: linear-gradient(90deg, var(--blue), transparent);
          border-radius: 2px;
        }
        
        .sector-title-red::after {
          background: linear-gradient(90deg, var(--red), transparent);
        }
        
        .sector-title-green::after {
          background: linear-gradient(90deg, var(--green), transparent);
        }

        .sector-updated {
          color: var(--gray-500);
          font-size: 12px;
          background: rgba(255,255,255,0.05);
          padding: 4px 8px;
          border-radius: 4px;
        }

        /* Heatmap Grid */
        .sector-heatmap-grid {
          display: grid;
          grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
          gap: 16px;
          perspective: 1200px;
        }

        .sector-heatmap-tile {
          border-radius: 10px;
          padding: 16px;
          display: flex;
          flex-direction: column;
          gap: 12px;
          transition: transform 0.4s cubic-bezier(0.34, 1.56, 0.64, 1), box-shadow 0.3s ease;
          transform-style: preserve-3d;
          cursor: pointer;
          position: relative;
          min-height: 100px;
        }

        .sector-heatmap-tile:hover {
          transform: translateY(-6px) rotateX(4deg) rotateY(-4deg);
          box-shadow: 0 12px 24px -10px rgba(0,0,0,0.6);
          z-index: 10;
        }

        .sector-heatmap-tile::after {
          content: '';
          position: absolute;
          inset: 0;
          background: inherit;
          filter: blur(15px);
          opacity: 0;
          transition: opacity 0.4s ease;
          z-index: -1;
          border-radius: inherit;
        }

        .sector-heatmap-tile:hover::after {
          opacity: 0.5;
        }

        .sector-tile-name {
          color: var(--gray-200);
          font-size: 14px;
          font-weight: 600;
          line-height: 1.2;
          text-shadow: 0 1px 2px rgba(0,0,0,0.5);
        }

        .sector-rate-text {
          font-size: 20px;
          font-weight: 700;
          line-height: 1;
          text-shadow: 0 1px 2px rgba(0,0,0,0.3);
        }

        .sector-tile-stock {
          color: var(--gray-300);
          font-size: 12px;
          margin-top: auto;
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
          background: rgba(0,0,0,0.2);
          padding: 4px 6px;
          border-radius: 4px;
          display: inline-block;
          width: fit-content;
          max-width: 100%;
        }

        /* Table Row Split */
        .sector-tables-row {
          display: grid;
          grid-template-columns: 1fr 1fr;
          gap: 24px;
        }
        @media (max-width: 1024px) {
          .sector-tables-row {
            grid-template-columns: 1fr;
          }
        }

        /* Tables */
        .sector-table-wrap {
          width: 100%;
          overflow-x: auto;
        }
        .sector-table {
          width: 100%;
          border-collapse: separate;
          border-spacing: 0 4px;
          text-align: left;
        }
        .sector-table th {
          color: var(--gray-400);
          font-weight: 500;
          font-size: 12px;
          padding: 0 12px 12px 12px;
          white-space: nowrap;
        }
        .sector-table td {
          padding: 14px 12px;
          font-size: 13px;
          color: var(--gray-200);
          background: rgba(255,255,255,0.02);
          transition: background-color 0.2s, transform 0.2s;
        }
        .sector-table td:first-child {
          border-top-left-radius: 6px;
          border-bottom-left-radius: 6px;
        }
        .sector-table td:last-child {
          border-top-right-radius: 6px;
          border-bottom-right-radius: 6px;
        }
        .sector-table tbody tr {
          transition: transform 0.2s ease;
        }
        .sector-table tbody tr:nth-child(even) td {
          background: linear-gradient(90deg, rgba(255,255,255,0.01), rgba(255,255,255,0.03));
        }
        .sector-table tbody tr:hover {
          transform: scale(1.01);
        }
        .sector-table tbody tr:hover td {
          background: rgba(255,255,255,0.06);
        }
        .sector-table td strong {
          color: var(--white);
          font-weight: 500;
          font-size: 14px;
        }

        /* Premium Shimmer */
        .sector-shimmer {
          background: linear-gradient(
            90deg,
            var(--gray-850) 0%,
            var(--gray-750) 50%,
            var(--gray-850) 100%
          );
          background-size: 200% 100%;
          animation: sectorShimmer 2s infinite linear;
          border-radius: 8px;
        }
        @keyframes sectorShimmer {
          0% { background-position: 200% 0; }
          100% { background-position: -200% 0; }
        }
        
        .sector-shimmer-grid {
          display: grid;
          grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
          gap: 16px;
        }

        .sector-chart-wrapper {
          margin-top: 20px;
        }
      `}</style>

      {/* Heatmap */}
      <section className="sector-panel">
        <div className="sector-header-wrapper">
          <div>
            <p className="sector-eyebrow"><Layers size={14} /> WICS 업종분류</p>
            <h2 className="sector-title">섹터 히트맵</h2>
          </div>
          {sectors?.updated_at && (
            <span className="sector-updated" style={mono}>갱신 {sectors.updated_at}</span>
          )}
        </div>
        
        {loading || !items.length ? (
          <div className="sector-shimmer-grid">
            {Array.from({ length: 12 }, (_, i) => <SectorShimmer key={i} height={100} />)}
          </div>
        ) : (
          <div className="sector-heatmap-grid">
            {items.map((s) => (
              <div
                key={s.code}
                className="sector-heatmap-tile"
                style={{
                  ...getGradientStyle(s.change_rate),
                  borderWidth: '1px',
                  borderStyle: 'solid'
                }}
              >
                <span className="sector-tile-name">{s.name}</span>
                <AnimatedRate value={s.change_rate} />
                {s.top_stock && <span className="sector-tile-stock">{s.top_stock}</span>}
              </div>
            ))}
          </div>
        )}
      </section>

      {/* Top / Bottom Performers */}
      <div className="sector-tables-row">
        <section className="sector-panel">
          <div className="sector-header-wrapper">
            <div>
              <p className="sector-eyebrow"><Flame size={14} color="var(--red)" /> 강세</p>
              <h2 className="sector-title sector-title-red">상위 5 업종</h2>
            </div>
          </div>
          
          {loading || !top5.length ? (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
              {[1,2,3,4,5].map(i => <SectorShimmer key={i} height={46} />)}
            </div>
          ) : (
            <div className="sector-table-wrap">
              <table className="sector-table">
                <thead><tr><th>순위</th><th>업종명</th><th>등락률</th><th>거래대금</th><th>대표종목</th></tr></thead>
                <tbody>
                  {top5.map((s, i) => (
                    <tr key={s.code}>
                      <td style={mono}>{i + 1}</td>
                      <td><strong>{s.name}</strong></td>
                      <td style={{ color: 'var(--green)', ...mono }}>
                        <AnimatedRate value={s.change_rate} />
                      </td>
                      <td style={mono}>{fmtVolume(s.volume)}</td>
                      <td>{s.top_stock}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>

        <section className="sector-panel">
          <div className="sector-header-wrapper">
            <div>
              <p className="sector-eyebrow"><Snowflake size={14} color="var(--blue)" /> 약세</p>
              <h2 className="sector-title sector-title-green">하위 5 업종</h2>
            </div>
          </div>
          
          {loading || !bottom5.length ? (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
              {[1,2,3,4,5].map(i => <SectorShimmer key={i} height={46} />)}
            </div>
          ) : (
            <div className="sector-table-wrap">
              <table className="sector-table">
                <thead><tr><th>순위</th><th>업종명</th><th>등락률</th><th>거래대금</th><th>대표종목</th></tr></thead>
                <tbody>
                  {bottom5.map((s, i) => (
                    <tr key={s.code}>
                      <td style={mono}>{i + 1}</td>
                      <td><strong>{s.name}</strong></td>
                      <td style={{ color: 'var(--red)', ...mono }}>
                        <AnimatedRate value={s.change_rate} />
                      </td>
                      <td style={mono}>{fmtVolume(s.volume)}</td>
                      <td>{s.top_stock}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      </div>

      {/* Full Sector Distribution Chart */}
      <section className="sector-panel">
        <div className="sector-header-wrapper">
          <div>
            <p className="sector-eyebrow"><TrendingUp size={14} /> 전체 업종</p>
            <h2 className="sector-title">섹터 등락률 분포</h2>
          </div>
        </div>
        
        {loading || !chartData.length ? (
          <SectorShimmer height={300} />
        ) : (
          <div className="sector-chart-wrapper">
            <ResponsiveContainer width="100%" height={Math.max(300, chartData.length * 28)}>
              <BarChart data={chartData} layout="vertical" margin={{ top: 10, right: 40, left: 10, bottom: 10 }}>
                <defs>
                  <linearGradient id="sectorGreenGrad" x1="0" y1="0" x2="1" y2="0">
                    <stop offset="0%" stopColor="var(--green)" stopOpacity={0.8}/>
                    <stop offset="100%" stopColor="var(--green)" stopOpacity={0.3}/>
                  </linearGradient>
                  <linearGradient id="sectorRedGrad" x1="0" y1="0" x2="1" y2="0">
                    <stop offset="0%" stopColor="var(--red)" stopOpacity={0.3}/>
                    <stop offset="100%" stopColor="var(--red)" stopOpacity={0.8}/>
                  </linearGradient>
                </defs>
                
                <CartesianGrid strokeDasharray="3 3" stroke="var(--gray-800)" horizontal={false} />
                <XAxis type="number" tick={{ fill: 'var(--gray-400)', fontSize: 12, fontFamily: 'var(--font-mono)' }} axisLine={{ stroke: 'var(--gray-700)' }} tickLine={false} tickFormatter={(v) => `${v}%`} />
                <YAxis dataKey="name" type="category" axisLine={false} tickLine={false} tick={{ fill: 'var(--gray-300)', fontSize: 12, fontWeight: 500, fontFamily: 'Inter, sans-serif' }} width={110} />
                <Tooltip cursor={{ fill: 'rgba(255,255,255,0.03)' }} contentStyle={chartTooltipStyle} formatter={(v) => [`${v > 0 ? '+' : ''}${v}%`, '등락률']} />
                
                <Bar dataKey="change_rate" radius={[0, 4, 4, 0]} barSize={18}>
                  {chartData.map((entry, i) => (
                    <Cell key={i} fill={entry.change_rate >= 0 ? 'url(#sectorGreenGrad)' : 'url(#sectorRedGrad)'} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        )}
      </section>
    </div>
  )
}
