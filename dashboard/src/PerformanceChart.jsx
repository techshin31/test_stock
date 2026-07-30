import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import {
  CHART_COLORS,
  chartAxisLine,
  chartAxisTick,
  chartCursor,
  chartGrid,
  chartTooltipStyle,
} from './chartTheme'

export default function PerformanceChart({ data }) {
  return (
    <ResponsiveContainer width="100%" height={220}>
      <AreaChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: -24 }}>
        <defs>
          <linearGradient id="colorFreshness" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={CHART_COLORS.accent} stopOpacity={0.22} />
            <stop offset="100%" stopColor={CHART_COLORS.accent} stopOpacity={0} />
          </linearGradient>
          <linearGradient id="colorRisk" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={CHART_COLORS.positive} stopOpacity={0.22} />
            <stop offset="100%" stopColor={CHART_COLORS.positive} stopOpacity={0} />
          </linearGradient>
        </defs>
        <CartesianGrid {...chartGrid} />
        <XAxis
          dataKey="index"
          tick={chartAxisTick}
          axisLine={chartAxisLine}
          tickLine={false}
        />
        <YAxis
          tick={chartAxisTick}
          axisLine={chartAxisLine}
          tickLine={false}
        />
        <Tooltip cursor={chartCursor} contentStyle={chartTooltipStyle} />
        <Area
          type="monotone"
          dataKey="freshness"
          name="신선 종목"
          stroke={CHART_COLORS.accent}
          strokeWidth={2}
          fillOpacity={1}
          fill="url(#colorFreshness)"
          isAnimationActive={false}
        />
        <Area
          type="monotone"
          dataKey="risk"
          name="완료 위험점검"
          stroke={CHART_COLORS.positive}
          strokeWidth={2}
          fillOpacity={1}
          fill="url(#colorRisk)"
          isAnimationActive={false}
        />
      </AreaChart>
    </ResponsiveContainer>
  )
}
