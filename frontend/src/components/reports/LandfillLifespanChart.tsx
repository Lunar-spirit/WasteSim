import { Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { formatTonnes } from '../../lib/format'
import type { SimulationYearly } from '../../types/api'

export default function LandfillLifespanChart({
  series,
  exhaustionYear,
}: {
  series: SimulationYearly[]
  exhaustionYear: number | null
}) {
  const data = series.map((y) => ({ year_index: y.year_index, remaining: y.landfill_remaining_tonnes }))
  const capacity = data.length ? Math.max(...data.map((d) => d.remaining)) : 0

  return (
    <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
      <h3 className="mb-1 text-sm font-semibold uppercase tracking-wide text-slate-500">
        Landfill Lifespan Countdown
      </h3>
      <p className="mb-4 text-xs text-slate-400">
        {exhaustionYear
          ? `Remaining capacity reaches zero in year ${exhaustionYear} (highlighted).`
          : capacity > 0
            ? 'Remaining capacity stays above zero for the full horizon.'
            : 'No completed run yet.'}
      </p>
      <ResponsiveContainer width="100%" height={280}>
        <BarChart data={data} margin={{ top: 8, right: 16, bottom: 0, left: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
          <XAxis dataKey="year_index" tickFormatter={(v) => `Yr ${v}`} stroke="#64748b" fontSize={12} />
          <YAxis stroke="#64748b" fontSize={12} tickFormatter={(v: number) => `${(v / 1000).toFixed(0)}k`} />
          <Tooltip formatter={(value) => formatTonnes(Number(value))} labelFormatter={(v) => `Year ${v}`} />
          <Bar dataKey="remaining" name="Landfill remaining (t)" radius={[3, 3, 0, 0]}>
            {data.map((d) => (
              <Cell key={d.year_index} fill={d.year_index === exhaustionYear ? '#ef4444' : d.remaining <= 0 ? '#fca5a5' : '#f59e0b'} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}
