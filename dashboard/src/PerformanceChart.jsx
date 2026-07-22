import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

export default function PerformanceChart({ data }) {
  return (
    <ResponsiveContainer width="100%" height={220}>
      <AreaChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: -24 }}>
        <defs>
          <linearGradient id="colorFreshness" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#3b82f6" stopOpacity={0.15} />
            <stop offset="100%" stopColor="#3b82f6" stopOpacity={0.0} />
          </linearGradient>
          <linearGradient id="colorRisk" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#22c55e" stopOpacity={0.15} />
            <stop offset="100%" stopColor="#22c55e" stopOpacity={0.0} />
          </linearGradient>
        </defs>
        <CartesianGrid stroke="rgba(255, 255, 255, 0.04)" strokeDasharray="3 3" vertical={false} />
        <XAxis
          dataKey="index"
          tick={{ fill: '#63636e', fontSize: 10, fontFamily: 'JetBrains Mono, monospace' }}
          axisLine={false}
          tickLine={false}
        />
        <YAxis
          tick={{ fill: '#63636e', fontSize: 10, fontFamily: 'JetBrains Mono, monospace' }}
          axisLine={false}
          tickLine={false}
        />
        <Tooltip
          contentStyle={{
            background: '#1c1c1f',
            border: '1px solid #2c2c30',
            borderRadius: '4px',
            color: '#d2d2d9',
            fontSize: '11px',
            fontFamily: 'JetBrains Mono, monospace',
            boxShadow: '0 4px 12px rgba(0, 0, 0, 0.4)',
          }}
        />
        <Area
          type="monotone"
          dataKey="freshness"
          name="신선 종목"
          stroke="#3b82f6"
          strokeWidth={1.5}
          fillOpacity={1}
          fill="url(#colorFreshness)"
        />
        <Area
          type="monotone"
          dataKey="risk"
          name="완료 위험점검"
          stroke="#22c55e"
          strokeWidth={1.5}
          fillOpacity={1}
          fill="url(#colorRisk)"
        />
      </AreaChart>
    </ResponsiveContainer>
  )
}
