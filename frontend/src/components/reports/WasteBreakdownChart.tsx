import {
  Area,
  AreaChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { formatTonnes } from '../../lib/format'

export interface WasteBreakdownYear {
  year_index: number
  organic: number
  plastic: number
  paper: number
  inert: number
}

const SERIES: { key: keyof Omit<WasteBreakdownYear, 'year_index'>; label: string; color: string }[] = [
  { key: 'organic', label: 'Organic', color: '#10b981' },
  { key: 'plastic', label: 'Plastic', color: '#f97316' },
  { key: 'paper', label: 'Paper', color: '#0ea5e9' },
  { key: 'inert', label: 'Inert (metal/glass/textile/e-waste/other)', color: '#94a3b8' },
]

export default function WasteBreakdownChart({ data }: { data: WasteBreakdownYear[] }) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
      <h3 className="mb-1 text-sm font-semibold uppercase tracking-wide text-slate-500">
        Waste Generation Breakdown
      </h3>
      <p className="mb-4 text-xs text-slate-400">
        20-year composition, split from each year's total generation (tonnes/year). Organic and plastic/paper
        come straight from the habitation's own composition drift; "inert" bundles metal, glass, textile,
        e-waste and other since the engine doesn't track those separately.
      </p>
      <ResponsiveContainer width="100%" height={320}>
        <AreaChart data={data} margin={{ top: 8, right: 16, bottom: 0, left: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
          <XAxis dataKey="year_index" tickFormatter={(v) => `Yr ${v}`} stroke="#64748b" fontSize={12} />
          <YAxis stroke="#64748b" fontSize={12} tickFormatter={(v: number) => `${(v / 1000).toFixed(0)}k`} />
          <Tooltip formatter={(value, name) => [formatTonnes(Number(value)), name]} labelFormatter={(v) => `Year ${v}`} />
          <Legend />
          {SERIES.map((s) => (
            <Area
              key={s.key}
              type="monotone"
              dataKey={s.key}
              name={s.label}
              stackId="waste"
              stroke={s.color}
              fill={s.color}
              fillOpacity={0.65}
            />
          ))}
        </AreaChart>
      </ResponsiveContainer>
    </div>
  )
}
