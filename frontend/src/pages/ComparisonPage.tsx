import { useMutation, useQuery } from '@tanstack/react-query'
import { GitCompare, Loader2 } from 'lucide-react'
import { useMemo, useState } from 'react'
import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { createComparison, fetchComparison, fetchComparisonDeltas, listSimulations } from '../api/endpoints'
import { useAppContext } from '../context/AppContext'
import { pushHistory, useHistory } from '../lib/history'

const RUN_COLOURS = ['#10b981', '#0ea5e9', '#f59e0b', '#a855f7']
const INDICATORS = ['total_cost_inr', 'landfilled_tpy', 'avg_coverage_pct']

export default function ComparisonPage() {
  const { currentHabitationId } = useAppContext()

  const runsQuery = useQuery({ queryKey: ['simulations', currentHabitationId], queryFn: () => listSimulations(currentHabitationId) })
  const completedRuns = (runsQuery.data ?? []).filter((r) => r.status === 'COMPLETED')

  const [selectedRunIds, setSelectedRunIds] = useState<string[]>([])

  function toggleRun(id: string) {
    setSelectedRunIds((prev) => {
      if (prev.includes(id)) return prev.filter((x) => x !== id)
      if (prev.length >= 4) return prev
      return [...prev, id]
    })
  }

  const history = useHistory('comparison', currentHabitationId)
  const [comparisonId, setComparisonId] = useState<string | null>(history[0] ?? null)

  const createMutation = useMutation({
    mutationFn: () => createComparison(selectedRunIds),
    onSuccess: (comparison) => {
      setComparisonId(comparison.id)
      pushHistory('comparison', currentHabitationId, comparison.id)
    },
  })

  const seriesQuery = useQuery({
    queryKey: ['comparison', comparisonId],
    queryFn: () => fetchComparison(comparisonId as string),
    enabled: !!comparisonId,
  })
  const deltasQuery = useQuery({
    queryKey: ['comparison-deltas', comparisonId],
    queryFn: () => fetchComparisonDeltas(comparisonId as string),
    enabled: !!comparisonId,
  })

  const [chartIndicator, setChartIndicator] = useState(INDICATORS[0])

  const chartData = useMemo(() => {
    const rows = seriesQuery.data?.series[chartIndicator] ?? []
    return rows.map((row) => ({ year_index: row.year_index, ...row.values }))
  }, [seriesQuery.data, chartIndicator])

  const runIds = seriesQuery.data?.run_ids ?? []

  function runLabel(id: string): string {
    const run = completedRuns.find((r) => r.id === id)
    return run?.label ?? id.slice(0, 8)
  }

  return (
    <div className="flex flex-col gap-6 p-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500">Multi-Run Comparison Matrix</h2>
        {history.length > 0 && (
          <label className="flex items-center gap-2 text-sm">
            <span className="text-slate-500">Past comparisons</span>
            <select value={comparisonId ?? ''} onChange={(e) => setComparisonId(e.target.value || null)} className="rounded-md border border-slate-300 px-2.5 py-1.5 text-sm">
              <option value="">New comparison</option>
              {history.map((id) => (
                <option key={id} value={id}>
                  {id.slice(0, 8)}…
                </option>
              ))}
            </select>
          </label>
        )}
      </div>

      <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
        <h3 className="mb-3 text-xs font-semibold uppercase tracking-wide text-slate-500">Run Selector (2–4 runs)</h3>
        <div className="flex flex-wrap gap-2">
          {completedRuns.map((run) => {
            const selected = selectedRunIds.includes(run.id)
            return (
              <button
                key={run.id}
                type="button"
                onClick={() => toggleRun(run.id)}
                className={`rounded-full border px-3 py-1.5 text-xs transition ${
                  selected ? 'border-emerald-400 bg-emerald-50 text-emerald-700' : 'border-slate-200 text-slate-500 hover:bg-slate-50'
                }`}
              >
                {run.label ?? run.id.slice(0, 8)} · {run.run_type}
              </button>
            )
          })}
          {completedRuns.length === 0 && <p className="text-sm text-slate-400">No completed runs yet for this habitation.</p>}
        </div>
        <button
          type="button"
          onClick={() => createMutation.mutate()}
          disabled={selectedRunIds.length < 2 || createMutation.isPending}
          className="mt-4 flex items-center justify-center gap-2 rounded-lg bg-emerald-600 px-4 py-2.5 text-sm font-semibold text-white transition hover:bg-emerald-700 disabled:opacity-60"
        >
          {createMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <GitCompare className="h-4 w-4" />}
          Compare Selected Runs
        </button>
        {createMutation.isError && <p className="mt-2 text-xs text-red-600">{(createMutation.error as Error).message}</p>}
      </div>

      {seriesQuery.data && (
        <>
          <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
            <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
              <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">Comparative Trajectory</h3>
              <div className="flex gap-1">
                {seriesQuery.data.indicators.map((ind) => (
                  <button
                    key={ind}
                    type="button"
                    onClick={() => setChartIndicator(ind)}
                    className={`rounded-full border px-2.5 py-1 text-xs transition ${
                      chartIndicator === ind ? 'border-emerald-300 bg-emerald-50 text-emerald-700' : 'border-slate-200 text-slate-500'
                    }`}
                  >
                    {ind}
                  </button>
                ))}
              </div>
            </div>
            <ResponsiveContainer width="100%" height={320}>
              <LineChart data={chartData} margin={{ top: 8, right: 16, bottom: 0, left: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                <XAxis dataKey="year_index" tickFormatter={(v) => `Yr ${v}`} stroke="#64748b" fontSize={12} />
                <YAxis stroke="#64748b" fontSize={12} />
                <Tooltip labelFormatter={(v) => `Year ${v}`} />
                <Legend formatter={(value) => runLabel(value as string)} />
                {runIds.map((id, idx) => (
                  <Line key={id} type="monotone" dataKey={id} name={id} stroke={RUN_COLOURS[idx % RUN_COLOURS.length]} strokeWidth={2} dot={false} connectNulls />
                ))}
              </LineChart>
            </ResponsiveContainer>
          </div>

          <div className="overflow-x-auto rounded-xl border border-slate-200 bg-white shadow-sm">
            <h3 className="border-b border-slate-100 px-5 py-3 text-xs font-semibold uppercase tracking-wide text-slate-500">
              Side-by-Side Diff Table (Δ vs. {runLabel(deltasQuery.data?.base_run_id ?? runIds[0])})
            </h3>
            {deltasQuery.data && (
              <table className="w-full text-xs">
                <thead>
                  <tr className="bg-slate-50 text-left text-slate-500">
                    <th className="px-5 py-2 font-medium">Indicator</th>
                    <th className="px-5 py-2 font-medium">Year</th>
                    {runIds.slice(1).map((id) => (
                      <th key={id} className="px-5 py-2 text-right font-medium">
                        {runLabel(id)}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {seriesQuery.data.indicators.flatMap((indicator) => {
                    const rows = deltasQuery.data!.deltas[indicator] ?? []
                    const lastRow = rows[rows.length - 1]
                    if (!lastRow) return []
                    return (
                      <tr key={indicator} className="border-t border-slate-50">
                        <td className="px-5 py-2 font-medium text-slate-700">{indicator}</td>
                        <td className="px-5 py-2 text-slate-500">{lastRow.year_index} (final)</td>
                        {runIds.slice(1).map((id) => {
                          const delta = lastRow[id] as number | null
                          const isCost = indicator.includes('cost') || indicator.includes('landfilled')
                          const good = delta != null && (isCost ? delta < 0 : delta > 0)
                          const bad = delta != null && (isCost ? delta > 0 : delta < 0)
                          return (
                            <td
                              key={id}
                              className={`px-5 py-2 text-right font-medium ${good ? 'text-emerald-600' : bad ? 'text-red-600' : 'text-slate-400'}`}
                            >
                              {delta == null ? '—' : (delta > 0 ? '+' : '') + delta.toLocaleString('en-IN', { maximumFractionDigits: 1 })}
                            </td>
                          )
                        })}
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            )}
          </div>
        </>
      )}
    </div>
  )
}
