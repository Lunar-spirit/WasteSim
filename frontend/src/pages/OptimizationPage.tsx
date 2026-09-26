import { useMutation, useQuery } from '@tanstack/react-query'
import { Loader2, Target, Zap } from 'lucide-react'
import { useMemo, useState } from 'react'
import { CartesianGrid, ResponsiveContainer, Scatter, ScatterChart, Tooltip, XAxis, YAxis } from 'recharts'
import {
  createOptimization,
  fetchOptimization,
  fetchOptimizationCandidates,
  fetchParetoFront,
  listSimulations,
  promoteOptimizationCandidate,
} from '../api/endpoints'
import { useAppContext } from '../context/AppContext'
import { useSelectedBaseRun } from '../lib/baseRun'
import { pushHistory, useHistory } from '../lib/history'
import type { AnalysisStatus, OptimizationCandidate } from '../types/api'

const POLL_STATUSES: AnalysisStatus[] = ['QUEUED', 'RUNNING']
const MAX_EVALUATIONS = 150

export default function OptimizationPage() {
  const { currentHabitationId, activeRunId, setActiveRunId } = useAppContext()

  const runsQuery = useQuery({ queryKey: ['simulations', currentHabitationId], queryFn: () => listSimulations(currentHabitationId) })
  const baseRuns = (runsQuery.data ?? []).filter((r) => r.run_type === 'BASE' && r.status === 'COMPLETED')
  const [effectiveBaseRunId, setBaseRunId] = useSelectedBaseRun(baseRuns, activeRunId)

  const [wCost, setWCost] = useState(50)
  const [wDiversion, setWDiversion] = useState(30)
  const [wCarbon, setWCarbon] = useState(20)
  const totalWeight = wCost + wDiversion + wCarbon

  const history = useHistory('optimization', currentHabitationId)
  const [optimizationId, setOptimizationId] = useState<string | null>(history[0] ?? null)

  const createMutation = useMutation({
    mutationFn: () =>
      createOptimization(
        currentHabitationId,
        effectiveBaseRunId as string,
        {
          MIN_COST: wCost / totalWeight,
          MAX_RECOVERY: wDiversion / totalWeight,
          MIN_GHG: wCarbon / totalWeight,
        },
        {},
        MAX_EVALUATIONS,
      ),
    onSuccess: (run) => {
      setOptimizationId(run.optimization_id)
      pushHistory('optimization', currentHabitationId, run.optimization_id)
    },
  })

  const optimizationQuery = useQuery({
    queryKey: ['optimization', optimizationId],
    queryFn: () => fetchOptimization(optimizationId as string),
    enabled: !!optimizationId,
    refetchInterval: (query) => {
      const status = query.state.data?.status
      return status && POLL_STATUSES.includes(status) ? 2000 : false
    },
  })

  const isRunning = optimizationQuery.data ? POLL_STATUSES.includes(optimizationQuery.data.status) : false
  const isCompleted = optimizationQuery.data?.status === 'COMPLETED'

  const paretoQuery = useQuery({
    queryKey: ['pareto', optimizationId],
    queryFn: () => fetchParetoFront(optimizationId as string),
    enabled: !!optimizationId && isCompleted,
  })
  const candidatesQuery = useQuery({
    queryKey: ['optimization-candidates', optimizationId],
    queryFn: () => fetchOptimizationCandidates(optimizationId as string),
    enabled: !!optimizationId && isCompleted,
  })

  const [selectedCandidate, setSelectedCandidate] = useState<OptimizationCandidate | null>(null)

  const promoteMutation = useMutation({
    mutationFn: () => promoteOptimizationCandidate(optimizationId as string, selectedCandidate?.id),
    onSuccess: (run) => setActiveRunId(run.id),
  })

  const scatterData = useMemo(
    () =>
      (paretoQuery.data ?? []).map((c) => ({
        x: c.objective_values.MIN_COST ?? 0,
        y: c.objective_values.MAX_RECOVERY ?? 0,
        candidate: c,
      })),
    [paretoQuery.data],
  )

  const progressPct = optimizationQuery.data ? Math.min(100, (optimizationQuery.data.candidates_evaluated / MAX_EVALUATIONS) * 100) : 0

  return (
    <div className="flex flex-col gap-6 p-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500">Multi-Objective Optimization Lab</h2>
        <div className="flex items-center gap-3">
          <label className="flex items-center gap-2 text-sm">
            <span className="text-slate-500">Base run</span>
            <select value={effectiveBaseRunId ?? ''} onChange={(e) => setBaseRunId(e.target.value)} className="rounded-md border border-slate-300 px-2.5 py-1.5 text-sm">
              {!effectiveBaseRunId && <option value="">Select a completed BASE run…</option>}
              {baseRuns.map((r) => (
                <option key={r.id} value={r.id}>
                  {r.label ?? r.id.slice(0, 8)}
                </option>
              ))}
            </select>
          </label>
          {history.length > 0 && (
            <label className="flex items-center gap-2 text-sm">
              <span className="text-slate-500">Past runs</span>
              <select value={optimizationId ?? ''} onChange={(e) => setOptimizationId(e.target.value || null)} className="rounded-md border border-slate-300 px-2.5 py-1.5 text-sm">
                <option value="">New optimization</option>
                {history.map((id) => (
                  <option key={id} value={id}>
                    {id.slice(0, 8)}…
                  </option>
                ))}
              </select>
            </label>
          )}
        </div>
      </div>

      <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
        <h3 className="mb-3 text-xs font-semibold uppercase tracking-wide text-slate-500">Objective Function Weights</h3>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
          <label className="flex flex-col gap-1 text-sm">
            <span className="flex justify-between font-medium text-slate-700">
              Minimize Cost <span className="text-emerald-600">{((wCost / totalWeight) * 100).toFixed(0)}%</span>
            </span>
            <input type="range" min="0" max="100" value={wCost} onChange={(e) => setWCost(Number(e.target.value))} className="accent-emerald-600" />
          </label>
          <label className="flex flex-col gap-1 text-sm">
            <span className="flex justify-between font-medium text-slate-700">
              Maximize Diversion <span className="text-emerald-600">{((wDiversion / totalWeight) * 100).toFixed(0)}%</span>
            </span>
            <input type="range" min="0" max="100" value={wDiversion} onChange={(e) => setWDiversion(Number(e.target.value))} className="accent-emerald-600" />
          </label>
          <label className="flex flex-col gap-1 text-sm">
            <span className="flex justify-between font-medium text-slate-700">
              Minimize Carbon <span className="text-emerald-600">{((wCarbon / totalWeight) * 100).toFixed(0)}%</span>
            </span>
            <input type="range" min="0" max="100" value={wCarbon} onChange={(e) => setWCarbon(Number(e.target.value))} className="accent-emerald-600" />
          </label>
        </div>
        <button
          type="button"
          onClick={() => createMutation.mutate()}
          disabled={!effectiveBaseRunId || createMutation.isPending || isRunning}
          className="mt-4 flex items-center justify-center gap-2 rounded-lg bg-emerald-600 px-4 py-2.5 text-sm font-semibold text-white transition hover:bg-emerald-700 disabled:opacity-60"
        >
          {createMutation.isPending || isRunning ? <Loader2 className="h-4 w-4 animate-spin" /> : <Target className="h-4 w-4" />}
          {isRunning ? 'Searching…' : 'Start Optimization Search'}
        </button>
        {createMutation.isError && <p className="mt-2 text-xs text-red-600">{(createMutation.error as Error).message}</p>}

        {optimizationQuery.data && (
          <div className="mt-4">
            <div className="mb-1 flex items-center justify-between text-xs text-slate-500">
              <span className="flex items-center gap-1">
                <Zap className="h-3 w-3" /> {optimizationQuery.data.status} — candidate {optimizationQuery.data.candidates_evaluated}/{MAX_EVALUATIONS}
              </span>
              {isRunning && <span>Evaluating candidate solutions…</span>}
            </div>
            <div className="h-2 w-full overflow-hidden rounded-full bg-slate-100">
              <div className="h-2 rounded-full bg-emerald-500 transition-all" style={{ width: `${progressPct}%` }} />
            </div>
            {optimizationQuery.data.infeasible_reason && (
              <p className="mt-2 text-xs text-red-600">{optimizationQuery.data.infeasible_reason}</p>
            )}
          </div>
        )}
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm lg:col-span-2">
          <h3 className="mb-3 text-xs font-semibold uppercase tracking-wide text-slate-500">Pareto Frontier — Cost vs. Diversion</h3>
          {!scatterData.length && <p className="text-sm text-slate-400">Run a search to see the Pareto frontier.</p>}
          {scatterData.length > 0 && (
            <ResponsiveContainer width="100%" height={340}>
              <ScatterChart margin={{ top: 8, right: 16, bottom: 8, left: 8 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                <XAxis type="number" dataKey="x" name="Cost (INR)" tickFormatter={(v) => `₹${(v / 1e7).toFixed(1)}Cr`} stroke="#64748b" fontSize={12} />
                <YAxis type="number" dataKey="y" name="Diversion %" stroke="#64748b" fontSize={12} />
                <Tooltip
                  cursor={{ strokeDasharray: '3 3' }}
                  content={({ active, payload }) => {
                    if (!active || !payload?.length) return null
                    const c = payload[0].payload.candidate as OptimizationCandidate
                    return (
                      <div className="rounded-lg border border-slate-200 bg-white p-2 text-xs shadow-lg">
                        <p className="font-medium">Candidate #{c.id}</p>
                        {Object.entries(c.decision_values).map(([k, v]) => (
                          <p key={k}>
                            {k}: {typeof v === 'number' ? v.toFixed(2) : String(v)}
                          </p>
                        ))}
                      </div>
                    )
                  }}
                />
                <Scatter
                  data={scatterData}
                  fill="#10b981"
                  onClick={(point) => setSelectedCandidate((point as unknown as { candidate: OptimizationCandidate }).candidate)}
                  cursor="pointer"
                />
              </ScatterChart>
            </ResponsiveContainer>
          )}
        </div>

        <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
          <h3 className="mb-3 text-xs font-semibold uppercase tracking-wide text-slate-500">Selected Candidate</h3>
          {!selectedCandidate && <p className="text-sm text-slate-400">Click a point on the Pareto frontier.</p>}
          {selectedCandidate && (
            <div className="flex flex-col gap-2 text-sm">
              <p className="font-medium text-slate-800">Candidate #{selectedCandidate.id}</p>
              <dl className="space-y-1 text-xs">
                {Object.entries(selectedCandidate.decision_values).map(([k, v]) => (
                  <div key={k} className="flex justify-between">
                    <dt className="text-slate-500">{k}</dt>
                    <dd className="font-medium text-slate-700">{typeof v === 'number' ? v.toFixed(2) : String(v)}</dd>
                  </div>
                ))}
              </dl>
              <button
                type="button"
                onClick={() => promoteMutation.mutate()}
                disabled={promoteMutation.isPending}
                className="mt-2 flex items-center justify-center gap-2 rounded-lg bg-slate-900 px-3.5 py-2 text-xs font-semibold text-white transition hover:bg-slate-800 disabled:opacity-60"
              >
                {promoteMutation.isPending && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
                Apply Candidate as New Baseline
              </button>
              {promoteMutation.isSuccess && <p className="text-xs text-emerald-600">Promoted — now the active run.</p>}
            </div>
          )}
          <p className="mt-3 text-[11px] text-slate-400">
            {candidatesQuery.data?.length ?? 0} candidates evaluated in total; {scatterData.length} on the Pareto front.
          </p>
        </div>
      </div>
    </div>
  )
}
