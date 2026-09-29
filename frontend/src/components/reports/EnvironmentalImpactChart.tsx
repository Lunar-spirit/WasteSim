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
import type { SimulationYearly } from '../../types/api'

export default function EnvironmentalImpactChart({ series }: { series: SimulationYearly[] }) {
  const data = series.map((y) => ({
    year_index: y.year_index,
    diversion_rate_pct: y.recovery_rate_pct,
    ghg_tco2e: y.ghg_tco2e,
  }))

  return (
    <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
      <h3 className="mb-1 text-sm font-semibold uppercase tracking-wide text-slate-500">Environmental Impact</h3>
      <p className="mb-4 text-xs text-slate-400">
        Diversion rate (treated + recovered, as a share of generation) against net GHG emissions — landfill
        methane minus what composting/recycling avoided; a bar below zero means avoided emissions outweighed
        landfill methane that year. Leachate risk isn't modeled anywhere in the simulation engine, so it isn't
        shown here rather than being estimated.
      </p>
      <ResponsiveContainer width="100%" height={300}>
        <ComposedChart data={data} margin={{ top: 8, right: 16, bottom: 0, left: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
          <XAxis dataKey="year_index" tickFormatter={(v) => `Yr ${v}`} stroke="#64748b" fontSize={12} />
          <YAxis
            yAxisId="pct"
            stroke="#64748b"
            fontSize={12}
            domain={[0, 100]}
            tickFormatter={(v: number) => `${v}%`}
            label={{ value: 'Diversion %', angle: -90, position: 'insideLeft', fontSize: 11, fill: '#64748b' }}
          />
          <YAxis
            yAxisId="ghg"
            orientation="right"
            stroke="#64748b"
            fontSize={12}
            tickFormatter={(v: number) => `${v.toLocaleString('en-IN')}t`}
            label={{ value: 'tCO2e', angle: 90, position: 'insideRight', fontSize: 11, fill: '#64748b' }}
          />
          <Tooltip
            formatter={(value, name) => [
              name === 'Diversion rate' ? `${Number(value).toFixed(1)}%` : `${Number(value).toLocaleString('en-IN')} tCO2e`,
              name,
            ]}
            labelFormatter={(v) => `Year ${v}`}
          />
          <Legend />
          <ReferenceLine yAxisId="ghg" y={0} stroke="#94a3b8" />
          <Bar yAxisId="pct" dataKey="diversion_rate_pct" name="Diversion rate" fill="#10b981" radius={[3, 3, 0, 0]} />
          <Line yAxisId="ghg" type="monotone" dataKey="ghg_tco2e" name="Net GHG (tCO2e)" stroke="#f97316" strokeWidth={2.5} dot={{ r: 3 }} />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  )
}
