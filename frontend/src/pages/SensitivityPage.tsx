import { useMutation, useQuery } from '@tanstack/react-query'
import { Activity, Loader2 } from 'lucide-react'
import { useMemo, useState } from 'react'
import {
  createSensitivitySweep,
  fetchParameterSet,
  fetchSensitivityAnalysis,
  fetchSensitivityTornado,
  fetchSimulationRun,
  listSimulations,
} from '../api/endpoints'
import { useAppContext } from '../context/AppContext'
import { pushHistory, useHistory } from '../lib/history'
import type { AnalysisStatus } from '../types/api'

// The backend catalogue marks a parameter's `is_sweepable` flag server-side
// only (not returned by GET /parameter-definitions) — this mirrors the
// real seeded set (checked directly against the dev database) rather than
// letting every parameter through and having the sweep 400 on submit.
const SWEEPABLE_PARAMS = [
  'waste_baseline.per_capita_generation_kg_day',
  'community_infrastructure.collection_vehicles_count',
  'community_infrastructure.collection_coverage_pct',
  'community_infrastructure.treatment_capacity_tpd',
  'natural_resources.annual_rainfall_mm',
  'cultural_context.segregation_practice_pct',
  'demography.annual_growth_rate_pct',
]

const POLL_STATUSES: AnalysisStatus[] = ['QUEUED', 'RUNNING']

function buildSweepValues(baseline: number, lowPct: number, highPct: number, steps: number): number[] {
  const low = baseline * (1 + lowPct / 100)
  const high = baseline * (1 + highPct / 100)
  if (steps <= 1) return [baseline]
  const values: number[] = []
  for (let i = 0; i < steps; i++) {
    values.push(low + ((high - low) * i) / (steps - 1))
  }
  return [...new Set(values.map((v) => Math.round(v * 1000) / 1000))]
}

export default function SensitivityPage() {
  const { currentHabitationId, activeRunId } = useAppContext()

  const runsQuery = useQuery({ queryKey: ['simulations', currentHabitationId], queryFn: () => listSimulations(currentHabitationId) })
  const baseRuns = (runsQuery.data ?? []).filter((r) => r.run_type === 'BASE' && r.status === 'COMPLETED')
  const [baseRunId, setBaseRunId] = useState<string | null>(activeRunId)
  const effectiveBaseRunId = baseRunId ?? activeRunId

  const baseRunQuery = useQuery({
    queryKey: ['simulation-run', effectiveBaseRunId],
    queryFn: () => fetchSimulationRun(effectiveBaseRunId as string),
    enabled: !!effectiveBaseRunId,
  })
  const parameterSetQuery = useQuery({
    queryKey: ['parameter-set', baseRunQuery.data?.parameter_set_id],
    queryFn: () => fetchParameterSet(baseRunQuery.data!.parameter_set_id),
    enabled: !!baseRunQuery.data?.parameter_set_id,
  })

  const [paramPath, setParamPath] = useState(SWEEPABLE_PARAMS[0])
  const [lowPct, setLowPct] = useState(-20)
  const [highPct, setHighPct] = useState(20)
  const [steps, setSteps] = useState(5)

  const baselineValue = useMemo(() => {
    const [category, key] = paramPath.split('.')
    // waste_baseline is a separate top-level field on ParameterSetDetail,
    // not nested under `categories` like every other category (see
    // ParameterSetDetailOut in app/parameters/schemas.py). Numeric values
    // that started as a DB Numeric/Decimal column also arrive JSON-encoded
    // as a string, not a number, so coerce rather than assume typeof.
    const value =
      category === 'waste_baseline'
        ? parameterSetQuery.data?.waste_baseline?.[key]
        : parameterSetQuery.data?.categories?.[category]?.[key]
    if (value === null || value === undefined) return null
    const num = Number(value)
    return Number.isFinite(num) ? num : null
  }, [parameterSetQuery.data, paramPath])

  const previewValues = baselineValue != null ? buildSweepValues(baselineValue, lowPct, highPct, steps) : []

  const history = useHistory('sensitivity', currentHabitationId)
  const [analysisId, setAnalysisId] = useState<string | null>(history[0] ?? null)

  const sweepMutation = useMutation({
    mutationFn: () => createSensitivitySweep(currentHabitationId, effectiveBaseRunId as string, paramPath, previewValues),
    onSuccess: (analysis) => {
      setAnalysisId(analysis.id)
      pushHistory('sensitivity', currentHabitationId, analysis.id)
    },
  })

  const analysisQuery = useQuery({
    queryKey: ['sensitivity-analysis', analysisId],
    queryFn: () => fetchSensitivityAnalysis(analysisId as string),
    enabled: !!analysisId,
    refetchInterval: (query) => {
      const status = query.state.data?.status
      return status && POLL_STATUSES.includes(status) ? 2000 : false
    },
  })

  const tornadoQuery = useQuery({
    queryKey: ['sensitivity-tornado', analysisId],
    queryFn: () => fetchSensitivityTornado(analysisId as string),
    enabled: !!analysisId && analysisQuery.data?.status === 'COMPLETED',
  })

  const maxAbsRange = Math.max(1, ...(tornadoQuery.data ?? []).map((r) => r.range))

  return (
    <div className="flex flex-col gap-6 p-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500">Sensitivity &amp; Tornado Analyzer</h2>
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
              <span className="text-slate-500">Past sweeps</span>
              <select value={analysisId ?? ''} onChange={(e) => setAnalysisId(e.target.value || null)} className="rounded-md border border-slate-300 px-2.5 py-1.5 text-sm">
                <option value="">New sweep</option>
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

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        {/* Configurator */}
        <div className="flex flex-col gap-4 rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
          <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">Parameter Sweep Configurator</h3>

          <label className="flex flex-col gap-1 text-sm">
            <span className="font-medium text-slate-700">Parameter</span>
            <select value={paramPath} onChange={(e) => setParamPath(e.target.value)} className="rounded-md border border-slate-300 px-3 py-2 text-sm">
              {SWEEPABLE_PARAMS.map((p) => (
                <option key={p} value={p}>
                  {p}
                </option>
              ))}
            </select>
          </label>
          <p className="text-xs text-slate-400">
            Baseline value: {baselineValue != null ? baselineValue : parameterSetQuery.isFetching ? 'loading…' : 'unavailable'}
          </p>

          <div className="grid grid-cols-3 gap-3">
            <label className="flex flex-col gap-1 text-sm">
              <span className="font-medium text-slate-700">Low bound (%)</span>
              <input type="number" value={lowPct} onChange={(e) => setLowPct(Number(e.target.value))} className="rounded-md border border-slate-300 px-2.5 py-2 text-sm" />
            </label>
            <label className="flex flex-col gap-1 text-sm">
              <span className="font-medium text-slate-700">High bound (%)</span>
              <input type="number" value={highPct} onChange={(e) => setHighPct(Number(e.target.value))} className="rounded-md border border-slate-300 px-2.5 py-2 text-sm" />
            </label>
            <label className="flex flex-col gap-1 text-sm">
              <span className="font-medium text-slate-700">Step count</span>
              <input type="number" min="2" max="25" value={steps} onChange={(e) => setSteps(Number(e.target.value))} className="rounded-md border border-slate-300 px-2.5 py-2 text-sm" />
            </label>
          </div>

          {previewValues.length > 0 && (
            <p className="text-xs text-slate-500">Evaluation points: {previewValues.join(', ')}</p>
          )}

          <button
            type="button"
            onClick={() => sweepMutation.mutate()}
            disabled={!effectiveBaseRunId || baselineValue == null || sweepMutation.isPending}
            className="mt-2 flex items-center justify-center gap-2 rounded-lg bg-emerald-600 px-4 py-2.5 text-sm font-semibold text-white transition hover:bg-emerald-700 disabled:opacity-60"
          >
            {sweepMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Activity className="h-4 w-4" />}
            Run Sweep
          </button>
          {sweepMutation.isError && <p className="text-xs text-red-600">{(sweepMutation.error as Error).message}</p>}
          {analysisQuery.data && (
            <p className="text-xs text-slate-500">
              Status: <span className="font-medium">{analysisQuery.data.status}</span>
              {POLL_STATUSES.includes(analysisQuery.data.status) && <Loader2 className="ml-1 inline h-3 w-3 animate-spin" />}
            </p>
          )}
        </div>

        {/* Elasticity table */}
        <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
          <h3 className="mb-3 text-xs font-semibold uppercase tracking-wide text-slate-500">Elasticity Coefficient Table</h3>
          {!analysisQuery.data && <p className="text-sm text-slate-400">Run a sweep to see per-point elasticity.</p>}
          {analysisQuery.data && analysisQuery.data.status !== 'COMPLETED' && (
            <p className="text-sm text-slate-400">Waiting for the sweep to complete…</p>
          )}
          {analysisQuery.data?.status === 'COMPLETED' && (
            <table className="w-full text-xs">
              <thead>
                <tr className="text-left text-slate-500">
                  <th className="py-1 font-medium">Swept value</th>
                  {analysisQuery.data.indicators.map((ind) => (
                    <th key={ind} className="py-1 font-medium">
                      {ind} elasticity
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {(analysisQuery.data.points ?? []).map((p) => (
                  <tr key={p.id} className="border-t border-slate-50">
                    <td className="py-1.5">{p.swept_value}</td>
                    {analysisQuery.data!.indicators.map((ind) => {
                      const e = p.elasticity?.[ind]
                      return (
                        <td key={ind} className="py-1.5">
                          {e != null ? Number(e).toFixed(3) : '—'}
                        </td>
                      )
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>

      {/* Tornado chart */}
      <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
        <h3 className="mb-4 text-xs font-semibold uppercase tracking-wide text-slate-500">
          Tornado Chart — indicators most affected by {paramPath}
        </h3>
        {!tornadoQuery.data?.length && <p className="text-sm text-slate-400">No completed sweep to chart yet.</p>}
        <div className="flex flex-col gap-2">
          {(tornadoQuery.data ?? []).map((row) => (
            <div key={row.indicator} className="flex items-center gap-3">
              <span className="w-48 shrink-0 text-right text-xs text-slate-600">{row.indicator}</span>
              <div className="relative h-5 flex-1 rounded bg-slate-100">
                <div
                  className="h-5 rounded bg-emerald-500/70"
                  style={{ width: `${Math.max(2, (row.range / maxAbsRange) * 100)}%` }}
                />
              </div>
              <span className="w-32 shrink-0 text-xs text-slate-500">
                {row.min_value.toLocaleString('en-IN', { maximumFractionDigits: 1 })} –{' '}
                {row.max_value.toLocaleString('en-IN', { maximumFractionDigits: 1 })}
                {row.max_abs_elasticity != null && ` (ε=${row.max_abs_elasticity.toFixed(2)})`}
              </span>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
