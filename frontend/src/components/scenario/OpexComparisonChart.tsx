import { Bar, CartesianGrid, ComposedChart, Legend, Line, ReferenceArea, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { formatCrores } from '../../lib/format'
import type { ComparativePreviewPoint } from '../../types/api'

export default function OpexComparisonChart({
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
        Monthly OPEX — Base Budget vs Scenario Cost
      </h3>
      <p className="mb-4 text-xs text-slate-400">
        Bars: base OPEX. Line: scenario OPEX — a coverage-only disruption (strike, breakdown) often shows
        lower cost during the shock itself, since less material moves through the paid collection chain; the
        real cost of that is the uncollected backlog, not this line.
      </p>
      <ResponsiveContainer width="100%" height={280}>
        <ComposedChart data={series} margin={{ top: 8, right: 16, bottom: 0, left: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
          <XAxis dataKey="month" tickFormatter={(v) => `Mo ${v}`} stroke="#64748b" fontSize={12} />
          <YAxis stroke="#64748b" fontSize={12} tickFormatter={(v: number) => formatCrores(v)} />
          <Tooltip formatter={(value) => formatCrores(Number(value))} labelFormatter={(v) => `Month ${v}`} />
          <Legend />
          <ReferenceArea x1={startMonth} x2={endMonth} fill="#f97316" fillOpacity={0.08} />
          <Bar dataKey="base_opex_inr" name="Base OPEX" fill="#94a3b8" radius={[2, 2, 0, 0]} />
          <Line type="monotone" dataKey="scenario_opex_inr" name="Scenario OPEX" stroke="#a855f7" strokeWidth={2.5} dot={false} />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  )
}
