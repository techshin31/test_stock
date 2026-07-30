export const CHART_COLORS = {
  accent: 'var(--blue)',
  positive: 'var(--green)',
  negative: 'var(--red)',
  warning: 'var(--amber)',
  text: 'var(--gray-100)',
  muted: 'var(--gray-300)',
  grid: 'var(--gray-700)',
  cursor: 'rgba(79, 143, 255, 0.08)',
}

export const chartAxisTick = {
  fill: CHART_COLORS.muted,
  fontSize: 11,
  fontFamily: 'var(--font-mono)',
}

export const chartAxisLine = { stroke: CHART_COLORS.grid }

export const chartGrid = {
  stroke: CHART_COLORS.grid,
  strokeDasharray: '3 3',
  vertical: false,
}

export const chartTooltipStyle = {
  backgroundColor: 'var(--gray-900)',
  border: '1px solid var(--gray-700)',
  borderRadius: '6px',
  color: CHART_COLORS.text,
  fontSize: '12px',
  fontFamily: 'var(--font-mono)',
  padding: '8px 10px',
}

export const chartLegendStyle = {
  paddingTop: '10px',
  color: CHART_COLORS.muted,
  fontSize: '11px',
  fontFamily: 'var(--font-sans)',
}

export const chartCursor = { fill: CHART_COLORS.cursor }

export function formatShortDate(value) {
  const date = String(value || '')
  return date.length >= 10 ? date.slice(5, 10) : date
}
