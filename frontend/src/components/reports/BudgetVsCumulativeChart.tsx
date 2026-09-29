import {
  Bar,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { formatCrores } from '../../lib/format'
import type { SimulationYearly } from '../../types/api'

export default function BudgetVsCumulativeChart({
  series,
  annualBudgetInr,
}: {
  series: SimulationYearly[]
  annualBudgetInr: number
}) {
  const data = series.reduce<{ year_index: number; annual_cost: number; cumulative_cost: number }[]>(
    (acc, y) => {
      const annual_cost = y.opex_inr + y.capex_inr
      const previous_cumulative = acc.length ? acc[acc.length - 1].cumulative_cost : 0
      acc.push({ year_index: y.year_index, annual_cost, cumulative_cost: previous_cumulative + annual_cost })
      return acc
    },
    [],
  )

  return (
    <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
      <h3 className="mb-1 text-sm font-semibold uppercase tracking-wide text-slate-500">
        Annual Budget vs Cumulative Cost
      </h3>
      <p className="mb-4 text-xs text-slate-400">
        Bars: that year's OPEX + CAPEX against the declared annual SWM budget (dashed line). Line: cumulative
        cost since year 1, right-hand axis.
      </p>
      <ResponsiveContainer width="100%" height={320}>
        <ComposedChart data={data} margin={{ top: 8, right: 16, bottom: 0, left: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
          <XAxis dataKey="year_index" tickFormatter={(v) => `Yr ${v}`} stroke="#64748b" fontSize={12} />
          <YAxis
            yAxisId="annual"
            stroke="#64748b"
            fontSize={12}
            tickFormatter={(v: number) => formatCrores(v)}
            label={{ value: 'Annual cost', angle: -90, position: 'insideLeft', fontSize: 11, fill: '#64748b' }}
          />
          <YAxis
            yAxisId="cumulative"
            orientation="right"
            stroke="#64748b"
            fontSize={12}
            tickFormatter={(v: number) => formatCrores(v)}
            label={{ value: 'Cumulative', angle: 90, position: 'insideRight', fontSize: 11, fill: '#64748b' }}
          />
          <Tooltip formatter={(value) => formatCrores(Number(value))} labelFormatter={(v) => `Year ${v}`} />
          <Legend />
          <ReferenceLine
            yAxisId="annual"
            y={annualBudgetInr}
            stroke="#ef4444"
            strokeDasharray="5 3"
            label={{ value: 'Annual budget', position: 'insideTopLeft', fontSize: 11, fill: '#ef4444' }}
          />
          <Bar yAxisId="annual" dataKey="annual_cost" name="Annual OPEX + CAPEX" fill="#0ea5e9" radius={[3, 3, 0, 0]} />
          <Line yAxisId="cumulative" type="monotone" dataKey="cumulative_cost" name="Cumulative cost" stroke="#10b981" strokeWidth={2.5} dot={false} />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  )
}
