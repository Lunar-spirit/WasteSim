import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  AlertTriangle,
  Download,
  IndianRupee,
  Loader2,
  Play,
  Recycle,
  Sparkles,
  Table2,
  TrendingUp,
  Truck,
} from 'lucide-react'
import { useEffect, useState } from 'react'
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import {
  autoPopulateHabitation,
  createReport,
  createSimulation,
  fetchBudgetLines,
  fetchReport,
  fetchReportDownloadUrl,
  fetchSimulationFindings,
  fetchSimulationResults,
  fetchSimulationRun,
} from '../api/endpoints'
import { useAppContext } from '../context/AppContext'
import { setDraftPsid } from '../lib/history'
import type { BudgetLine, ReportStatus, RunStatus, SimulationYearly } from '../types/api'

const HORIZON_YEARS = 10

function formatCrores(value: number): string {
  return `₹${(value / 1e7).toFixed(2)} Cr`
}

function formatInr(value: number): string {
  return `₹${value.toLocaleString('en-IN', { maximumFractionDigits: 0 })}`
}

const RUN_POLL_STATUSES: RunStatus[] = ['QUEUED', 'RUNNING']
const REPORT_POLL_STATUSES: ReportStatus[] = ['QUEUED', 'GENERATING']

type ChartIndicator = keyof Pick<
  SimulationYearly,
  'total_cost_inr' | 'waste_collected_tpy' | 'landfill_remaining_tonnes' | 'ghg_tco2e'
>

const INDICATOR_OPTIONS: { key: ChartIndicator; label: string; format: (v: number) => string }[] = [
  { key: 'total_cost_inr', label: 'Total Cost (INR)', format: formatInr },
  { key: 'waste_collected_tpy', label: 'Waste Collected (TPY)', format: (v) => `${v.toLocaleString('en-IN')} t` },
  { key: 'landfill_remaining_tonnes', label: 'Landfill Remaining (t)', format: (v) => `${v.toLocaleString('en-IN')} t` },
  { key: 'ghg_tco2e', label: 'GHG Emissions (tCO2e)', format: (v) => `${v.toLocaleString('en-IN')} t` },
]

const BUDGET_COLOURS: Record<string, string> = {
  COLLECTION: '#0ea5e9',
  TRANSPORT: '#6366f1',
  TREATMENT: '#10b981',
  DISPOSAL: '#f97316',
  FLEET_PURCHASE: '#a855f7',
  INFRASTRUCTURE: '#64748b',
  ADMIN: '#eab308',
  AWARENESS: '#ec4899',
}

function KpiCard({ icon, label, value }: { icon: React.ReactNode; label: string; value: string }) {
  return (
    <div className="flex items-center gap-3 rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
      <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-slate-50">{icon}</div>
      <div>
        <p className="text-xs font-medium uppercase tracking-wide text-slate-400">{label}</p>
        <p className="text-lg font-semibold text-slate-900">{value}</p>
      </div>
    </div>
  )
}

function TrajectoryTab({ series, isLoading }: { series: SimulationYearly[]; isLoading: boolean }) {
  const [indicator, setIndicator] = useState<ChartIndicator>('total_cost_inr')
  const active = INDICATOR_OPTIONS.find((o) => o.key === indicator)!

  return (
    <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500">10-Year Trajectory</h2>
        <div className="flex flex-wrap gap-1">
          {INDICATOR_OPTIONS.map((opt) => (
            <button
              key={opt.key}
              type="button"
              onClick={() => setIndicator(opt.key)}
              className={`rounded-full border px-2.5 py-1 text-xs transition ${
                indicator === opt.key ? 'border-emerald-300 bg-emerald-50 text-emerald-700' : 'border-slate-200 text-slate-500 hover:bg-slate-50'
              }`}
            >
              {opt.label}
            </button>
          ))}
        </div>
      </div>
      {isLoading && <div className="flex h-80 items-center justify-center text-sm text-slate-400">Loading results…</div>}
      {!isLoading && series.length === 0 && (
        <div className="flex h-80 items-center justify-center text-sm text-slate-400">No completed run yet.</div>
      )}
      {series.length > 0 && (
        <ResponsiveContainer width="100%" height={340}>
          <LineChart data={series} margin={{ top: 8, right: 16, bottom: 0, left: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
            <XAxis dataKey="year_index" tickFormatter={(v) => `Yr ${v}`} stroke="#64748b" fontSize={12} />
            <YAxis stroke="#64748b" fontSize={12} tickFormatter={(v: number) => (v > 100000 ? `${(v / 1e5).toFixed(0)}L` : `${v}`)} />
            <Tooltip formatter={(value: number) => active.format(value)} labelFormatter={(v) => `Year ${v}`} />
            <Legend />
            <Line type="monotone" dataKey={indicator} name={active.label} stroke="#10b981" strokeWidth={2.5} dot={{ r: 3 }} />
          </LineChart>
        </ResponsiveContainer>
      )}
    </div>
  )
}

function BudgetTab({ runId }: { runId: string | null }) {
  const budgetQuery = useQuery({
    queryKey: ['budget-lines', runId],
    queryFn: () => fetchBudgetLines(runId as string),
    enabled: !!runId,
  })

  const [expandedYear, setExpandedYear] = useState<number | null>(null)

  if (!runId) return <div className="rounded-xl border border-slate-200 bg-white p-8 text-center text-sm text-slate-400">Run a simulation first.</div>
  if (budgetQuery.isLoading) return <div className="flex justify-center p-8"><Loader2 className="h-5 w-5 animate-spin text-slate-400" /></div>

  const lines = budgetQuery.data ?? []
  const byYear = new Map<number, BudgetLine[]>()
  for (const line of lines) {
    const arr = byYear.get(line.year_index) ?? []
    arr.push(line)
    byYear.set(line.year_index, arr)
  }
  const years = [...byYear.keys()].sort((a, b) => a - b)

  return (
    <div className="rounded-xl border border-slate-200 bg-white shadow-sm">
      <h2 className="border-b border-slate-100 px-5 py-4 text-sm font-semibold uppercase tracking-wide text-slate-500">
        Line-Item Budget Sheet
      </h2>
      {years.length === 0 && <p className="p-5 text-sm text-slate-400">No budget lines recorded for this run.</p>}
      <div className="divide-y divide-slate-100">
        {years.map((year) => {
          const yearLines = byYear.get(year) ?? []
          const yearTotal = yearLines.reduce((s, l) => s + l.amount_inr, 0)
          const isOpen = expandedYear === year
          return (
            <div key={year}>
              <button
                type="button"
                onClick={() => setExpandedYear(isOpen ? null : year)}
                className="flex w-full items-center justify-between px-5 py-3 text-left text-sm hover:bg-slate-50"
              >
                <span className="font-medium text-slate-700">Year {year}</span>
                <span className="text-slate-500">{formatInr(yearTotal)}</span>
              </button>
              {isOpen && (
                <table className="w-full text-xs">
                  <thead>
                    <tr className="bg-slate-50 text-left text-slate-500">
                      <th className="px-5 py-1.5 font-medium">Category</th>
                      <th className="px-5 py-1.5 font-medium">Kind</th>
                      <th className="px-5 py-1.5 text-right font-medium">Amount</th>
                      <th className="px-5 py-1.5 text-right font-medium">Discounted (NPV)</th>
                    </tr>
                  </thead>
                  <tbody>
                    {yearLines.map((line, idx) => (
                      <tr key={idx} className="border-t border-slate-50">
                        <td className="px-5 py-1.5">
                          <span
                            className="mr-1.5 inline-block h-2 w-2 rounded-full"
                            style={{ backgroundColor: BUDGET_COLOURS[line.category] ?? '#94a3b8' }}
                          />
                          {line.category}
                        </td>
                        <td className="px-5 py-1.5 text-slate-500">{line.kind}</td>
                        <td className="px-5 py-1.5 text-right text-slate-700">{formatInr(line.amount_inr)}</td>
                        <td className="px-5 py-1.5 text-right text-slate-500">{formatInr(line.discounted_inr)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}

function FindingsTab({ runId }: { runId: string | null }) {
  const findingsQuery = useQuery({
    queryKey: ['findings', runId],
    queryFn: () => fetchSimulationFindings(runId as string),
    enabled: !!runId,
  })

  if (!runId) return <div className="rounded-xl border border-slate-200 bg-white p-8 text-center text-sm text-slate-400">Run a simulation first.</div>
  if (findingsQuery.isLoading) return <div className="flex justify-center p-8"><Loader2 className="h-5 w-5 animate-spin text-slate-400" /></div>

  const findings = findingsQuery.data ?? []
  const severityStyle: Record<string, string> = {
    CRITICAL: 'border-red-200 bg-red-50 text-red-800',
    WARNING: 'border-amber-200 bg-amber-50 text-amber-800',
    INFO: 'border-sky-200 bg-sky-50 text-sky-800',
  }

  return (
    <div className="flex flex-col gap-3">
      {findings.length === 0 && (
        <div className="rounded-xl border border-slate-200 bg-white p-8 text-center text-sm text-slate-400">
          No findings recorded — engine did not flag any operational alerts for this run.
        </div>
      )}
      {findings.map((f, idx) => (
        <div key={idx} className={`flex items-start gap-3 rounded-xl border p-4 text-sm shadow-sm ${severityStyle[f.severity] ?? 'border-slate-200 bg-white'}`}>
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
          <div>
            <p className="font-medium">{f.message}</p>
            <p className="text-xs opacity-70">
              {f.code} {f.year_index != null && `· Year ${f.year_index}`} {f.numeric_value != null && `· ${f.numeric_value}`}
            </p>
          </div>
        </div>
      ))}
    </div>
  )
}

export default function SimulationPage() {
  const { currentHabitationId, activeRunId, setActiveRunId } = useAppContext()
  const queryClient = useQueryClient()
  const [tab, setTab] = useState<'trajectory' | 'budget' | 'findings'>('trajectory')

  const [perCapitaKgDay, setPerCapitaKgDay] = useState(0.38)
  const [vehicleCount, setVehicleCount] = useState(4)
  const [coveragePct, setCoveragePct] = useState(85)
  const [annualBudgetInr, setAnnualBudgetInr] = useState(25_00_000)
  const [autoPopulateStatus, setAutoPopulateStatus] = useState<string | null>(null)

  const autoPopulateMutation = useMutation({
    mutationFn: () => autoPopulateHabitation(currentHabitationId),
    onSuccess: (result) => {
      const automated = (result.automated_categories as string[] | undefined) ?? []
      const skipped = (result.skipped_categories as { category: string }[] | undefined) ?? []
      setAutoPopulateStatus(
        `Auto-populated ${automated.length} field(s)` +
          (skipped.length ? `, skipped ${skipped.length} (external service unavailable)` : ''),
      )
      // Shared with GIS Studio and the Parameters page: record which draft
      // parameter set auto-populate just wrote into, so Parameters reuses
      // it instead of starting a second, blank draft.
      const psid = result.parameter_set_id as string | undefined
      if (psid) {
        setDraftPsid(currentHabitationId, psid)
        queryClient.invalidateQueries({ queryKey: ['parameter-set', psid] })
      }
    },
    onError: (error: Error) => setAutoPopulateStatus(`Auto-populate failed: ${error.message}`),
  })

  const runMutation = useMutation({
    mutationFn: () =>
      createSimulation(currentHabitationId, {
        horizon_years: HORIZON_YEARS,
        label: 'SWMS Lite dashboard run',
        param_overrides: {
          'waste_baseline.per_capita_generation_kg_day': perCapitaKgDay,
          'community_infrastructure.collection_vehicles_count': vehicleCount,
          'community_infrastructure.collection_coverage_pct': coveragePct,
          'economic_conditions.swm_annual_budget': annualBudgetInr,
        },
      }),
    onSuccess: (run) => setActiveRunId(run.id),
  })

  const runStatusQuery = useQuery({
    queryKey: ['simulation-run', activeRunId],
    queryFn: () => fetchSimulationRun(activeRunId as string),
    enabled: activeRunId !== null,
    refetchInterval: (query) => {
      const status = query.state.data?.status
      return status && RUN_POLL_STATUSES.includes(status) ? 2000 : false
    },
  })

  const isRunInProgress = runStatusQuery.data ? RUN_POLL_STATUSES.includes(runStatusQuery.data.status) : false
  const isRunCompleted = runStatusQuery.data?.status === 'COMPLETED'

  const resultsQuery = useQuery({
    queryKey: ['simulation-results', activeRunId],
    queryFn: () => fetchSimulationResults(activeRunId as string),
    enabled: activeRunId !== null && isRunCompleted,
  })

  const series = resultsQuery.data?.series ?? []
  const totalCostInr = series.reduce((sum, row) => sum + row.total_cost_inr, 0)
  const opexInr = series.reduce((sum, row) => sum + row.opex_inr, 0)
  const capexInr = series.reduce((sum, row) => sum + row.capex_inr, 0)
  const avgCoveragePct = series.length ? series.reduce((sum, row) => sum + row.avg_coverage_pct, 0) / series.length : 0
  const diversionRatePct = series.length ? series[series.length - 1].recovery_rate_pct : 0
  const peakVehicleDeficit = series.length ? Math.max(...series.map((r) => r.peak_vehicle_shortfall)) : 0

  const [reportId, setReportId] = useState<string | null>(null)
  const createReportMutation = useMutation({
    mutationFn: () => createReport({ runId: activeRunId as string }, 'PDF'),
    onSuccess: (report) => setReportId(report.id),
  })
  const reportStatusQuery = useQuery({
    queryKey: ['report', reportId],
    queryFn: () => fetchReport(reportId as string),
    enabled: reportId !== null,
    refetchInterval: (query) => {
      const status = query.state.data?.status
      return status && REPORT_POLL_STATUSES.includes(status) ? 2000 : false
    },
  })
  const downloadMutation = useMutation({
    mutationFn: () => fetchReportDownloadUrl(reportId as string),
    onSuccess: (download) => {
      window.open(download.url, '_blank', 'noopener')
      setReportId(null)
      queryClient.removeQueries({ queryKey: ['report', reportId] })
    },
  })
  const isReportReady = reportStatusQuery.data?.status === 'READY'
  const isReportGenerating = reportId !== null && !isReportReady

  useEffect(() => {
    if (isReportReady && reportId) downloadMutation.mutate()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isReportReady, reportId])

  return (
    <div className="grid grid-cols-1 gap-6 p-6 lg:grid-cols-3">
      {/* LEFT: parameter controller */}
      <section className="flex flex-col gap-4 rounded-xl border border-slate-200 bg-white p-5 shadow-sm lg:col-span-1">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500">Parameter Controller</h2>

        <button
          type="button"
          onClick={() => autoPopulateMutation.mutate()}
          disabled={autoPopulateMutation.isPending}
          className="flex items-center justify-center gap-2 rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-2.5 text-sm font-medium text-emerald-700 transition hover:bg-emerald-100 disabled:opacity-60"
        >
          {autoPopulateMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}
          Auto-Populate Defaults
        </button>
        {autoPopulateStatus && <p className="text-xs text-slate-500">{autoPopulateStatus}</p>}

        <div className="mt-2 flex flex-col gap-3">
          <label className="flex flex-col gap-1 text-sm">
            <span className="font-medium text-slate-700">Per-capita waste generation (kg/day)</span>
            <input type="number" step="0.01" min="0" value={perCapitaKgDay} onChange={(e) => setPerCapitaKgDay(Number(e.target.value))} className="rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500" />
          </label>
          <label className="flex flex-col gap-1 text-sm">
            <span className="font-medium text-slate-700">Vehicle fleet count</span>
            <input type="number" step="1" min="0" value={vehicleCount} onChange={(e) => setVehicleCount(Number(e.target.value))} className="rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500" />
          </label>
          <label className="flex flex-col gap-1 text-sm">
            <span className="font-medium text-slate-700">Target collection coverage (%)</span>
            <input type="number" step="1" min="0" max="100" value={coveragePct} onChange={(e) => setCoveragePct(Number(e.target.value))} className="rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500" />
          </label>
          <label className="flex flex-col gap-1 text-sm">
            <span className="font-medium text-slate-700">Annual SWM budget (INR)</span>
            <input type="number" step="10000" min="0" value={annualBudgetInr} onChange={(e) => setAnnualBudgetInr(Number(e.target.value))} className="rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500" />
          </label>
        </div>

        <button
          type="button"
          onClick={() => runMutation.mutate()}
          disabled={runMutation.isPending || isRunInProgress}
          className="mt-2 flex items-center justify-center gap-2 rounded-lg bg-emerald-600 px-4 py-3 text-sm font-semibold text-white shadow-sm transition hover:bg-emerald-700 disabled:cursor-not-allowed disabled:opacity-60"
        >
          {runMutation.isPending || isRunInProgress ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
          {isRunInProgress ? `Simulation ${runStatusQuery.data?.status.toLowerCase()}…` : 'Run Simulation'}
        </button>
        {runMutation.isError && <p className="text-xs text-red-600">{(runMutation.error as Error).message}</p>}
        {runStatusQuery.data?.status === 'FAILED' && <p className="text-xs text-red-600">Run failed: {runStatusQuery.data.error_detail}</p>}

        <div className="mt-2 flex items-center justify-between rounded-lg border border-slate-200 p-3">
          <div>
            <p className="text-xs font-medium text-slate-600">Detailed Project Report</p>
            <p className="text-[11px] text-slate-400">PDF of this run's findings & yearly results.</p>
          </div>
          <button
            type="button"
            onClick={() => createReportMutation.mutate()}
            disabled={!activeRunId || !isRunCompleted || createReportMutation.isPending || isReportGenerating}
            className="flex items-center gap-1.5 rounded-lg bg-slate-900 px-3 py-2 text-xs font-medium text-white transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {createReportMutation.isPending || isReportGenerating ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Download className="h-3.5 w-3.5" />}
            {isReportGenerating ? 'Generating…' : 'Download'}
          </button>
        </div>
      </section>

      {/* RIGHT: results & visuals */}
      <section className="flex flex-col gap-6 lg:col-span-2">
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-3 xl:grid-cols-5">
          <KpiCard icon={<IndianRupee className="h-5 w-5 text-emerald-600" />} label="10-Year NPV Cost" value={series.length ? formatCrores(totalCostInr) : '—'} />
          <KpiCard icon={<Table2 className="h-5 w-5 text-sky-600" />} label="OPEX / CAPEX" value={series.length ? `${formatCrores(opexInr)} / ${formatCrores(capexInr)}` : '—'} />
          <KpiCard icon={<TrendingUp className="h-5 w-5 text-sky-600" />} label="Avg Coverage" value={series.length ? `${avgCoveragePct.toFixed(1)}%` : '—'} />
          <KpiCard icon={<Recycle className="h-5 w-5 text-amber-600" />} label="Landfill Diversion" value={series.length ? `${diversionRatePct.toFixed(1)}%` : '—'} />
          <KpiCard icon={<Truck className="h-5 w-5 text-red-500" />} label="Peak Fleet Deficit" value={series.length ? `${peakVehicleDeficit} vehicles` : '—'} />
        </div>

        <div className="flex items-center gap-1 rounded-lg bg-slate-100 p-1 self-start">
          {(['trajectory', 'budget', 'findings'] as const).map((t) => (
            <button
              key={t}
              type="button"
              onClick={() => setTab(t)}
              className={`rounded-md px-3.5 py-1.5 text-sm font-medium capitalize transition ${
                tab === t ? 'bg-white text-slate-900 shadow-sm' : 'text-slate-500 hover:text-slate-700'
              }`}
            >
              {t === 'trajectory' ? 'Trajectory Graphs' : t === 'budget' ? 'Line-Item Budget' : 'Findings & Alerts'}
            </button>
          ))}
        </div>

        {tab === 'trajectory' && <TrajectoryTab series={series} isLoading={resultsQuery.isLoading && !!activeRunId && isRunCompleted} />}
        {tab === 'budget' && <BudgetTab runId={isRunCompleted ? activeRunId : null} />}
        {tab === 'findings' && <FindingsTab runId={isRunCompleted ? activeRunId : null} />}
      </section>
    </div>
  )
}
