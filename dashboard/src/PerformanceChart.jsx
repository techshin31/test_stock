import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

export default function PerformanceChart({ data }) {
  return (
    <ResponsiveContainer width="100%" height={240}>
      <LineChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: -20 }}>
        <CartesianGrid stroke="#263343" strokeDasharray="3 3" vertical={false} />
        <XAxis dataKey="index" tick={{ fill: '#7f8d9c', fontSize: 11 }} axisLine={false} tickLine={false} />
        <YAxis tick={{ fill: '#7f8d9c', fontSize: 11 }} axisLine={false} tickLine={false} />
        <Tooltip contentStyle={{ background: '#17212d', border: '1px solid #263343', borderRadius: 10 }} />
        <Line type="monotone" dataKey="freshness" name="신선 종목" stroke="#52a8ff" strokeWidth={2} dot={false} />
        <Line type="monotone" dataKey="risk" name="완료 위험점검" stroke="#45c486" strokeWidth={2} dot={false} />
      </LineChart>
    </ResponsiveContainer>
  )
}
