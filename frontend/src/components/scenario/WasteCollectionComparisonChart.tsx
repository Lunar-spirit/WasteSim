import {
  Area,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  ReferenceArea,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import type { ComparativePreviewPoint } from '../../types/api'

export default function WasteCollectionComparisonChart({
  series,
  startMonth,
  endMonth,
}: {
  series: ComparativePreviewPoint[]
  startMonth: number
  endMonth: number
}) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
      <h3 className="mb-1 text-sm font-semibold uppercase tracking-wide text-slate-500">
        Monthly Waste Collection — Base vs Scenario
      </h3>
      <p className="mb-4 text-xs text-slate-400">
        The shaded band marks the disruption window. The scenario line's dip below base is the acute
        collection trough; a gap that never closes shows the shock outlasting this run's own horizon.
      </p>
      <ResponsiveContainer width="100%" height={280}>
        <ComposedChart data={series} margin={{ top: 8, right: 16, bottom: 0, left: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
          <XAxis dataKey="month" tickFormatter={(v) => `Mo ${v}`} stroke="#64748b" fontSize={12} />
          <YAxis stroke="#64748b" fontSize={12} tickFormatter={(v: number) => `${v.toFixed(0)}t`} />
          <Tooltip
            formatter={(value, name) => [`${Number(value).toFixed(2)} t/day`, name]}
            labelFormatter={(v) => `Month ${v}`}
          />
          <Legend />
          <ReferenceArea x1={startMonth} x2={endMonth} fill="#f97316" fillOpacity={0.08} />
          <Area
            type="monotone"
            dataKey="base_collected_tpd"
            name="Base"
            stroke="#0ea5e9"
            fill="#0ea5e9"
            fillOpacity={0.12}
          />
          <Line type="monotone" dataKey="scenario_collected_tpd" name="Scenario" stroke="#ef4444" strokeWidth={2.5} dot={false} />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  )
}
