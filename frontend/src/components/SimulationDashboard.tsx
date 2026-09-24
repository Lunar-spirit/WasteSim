import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Download, IndianRupee, Loader2, Play, Recycle, Sparkles, TrendingUp } from 'lucide-react'
import { useEffect, useState } from 'react'
import {
  Bar,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import {
  autoPopulateHabitation,
  createReport,
  createSimulation,
  fetchReport,
  fetchReportDownloadUrl,
  fetchSimulationResults,
  fetchSimulationRun,
} from '../api/endpoints'
import { useAppContext } from '../context/AppContext'
import type { ReportStatus, RunStatus } from '../types/api'

const HORIZON_YEARS = 10

function formatCrores(value: number): string {
  return `₹${(value / 1e7).toFixed(2)} Cr`
}

function formatInr(value: number): string {
  return `₹${value.toLocaleString('en-IN', { maximumFractionDigits: 0 })}`
}

const RUN_POLL_STATUSES: RunStatus[] = ['QUEUED', 'RUNNING']
const REPORT_POLL_STATUSES: ReportStatus[] = ['QUEUED', 'GENERATING']

export default function SimulationDashboard() {
  const { currentHabitationId, activeRunId, setActiveRunId } = useAppContext()
  const queryClient = useQueryClient()

  // --- Left column: parameter form -----------------------------------------
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
    onSuccess: (run) => {
      setActiveRunId(run.id)
    },
  })

  // --- Right column: poll the active run, then fetch its results -----------
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
  const avgCoveragePct = series.length ? series.reduce((sum, row) => sum + row.avg_coverage_pct, 0) / series.length : 0
  const diversionRatePct = series.length ? series[series.length - 1].recovery_rate_pct : 0

  // --- Bottom action: generate + download the PDF report -------------------
  const [reportId, setReportId] = useState<string | null>(null)

  const createReportMutation = useMutation({
    mutationFn: () => createReport(activeRunId as string, 'PDF'),
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

  // Side effect (triggering the download mutation), not a render-time call —
  // fires exactly once per reportId transitioning to READY.
  useEffect(() => {
    if (isReportReady && reportId) {
      downloadMutation.mutate()
    }
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
            <input
              type="number"
              step="0.01"
              min="0"
              value={perCapitaKgDay}
              onChange={(e) => setPerCapitaKgDay(Number(e.target.value))}
              className="rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500"
            />
          </label>

          <label className="flex flex-col gap-1 text-sm">
            <span className="font-medium text-slate-700">Vehicle fleet count</span>
            <input
              type="number"
              step="1"
              min="0"
              value={vehicleCount}
              onChange={(e) => setVehicleCount(Number(e.target.value))}
              className="rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500"
            />
          </label>

          <label className="flex flex-col gap-1 text-sm">
            <span className="font-medium text-slate-700">Target collection coverage (%)</span>
            <input
              type="number"
              step="1"
              min="0"
              max="100"
              value={coveragePct}
              onChange={(e) => setCoveragePct(Number(e.target.value))}
              className="rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500"
            />
          </label>

          <label className="flex flex-col gap-1 text-sm">
            <span className="font-medium text-slate-700">Annual SWM budget (INR)</span>
            <input
              type="number"
              step="10000"
              min="0"
              value={annualBudgetInr}
              onChange={(e) => setAnnualBudgetInr(Number(e.target.value))}
              className="rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500"
            />
          </label>
        </div>

        <button
          type="button"
          onClick={() => runMutation.mutate()}
          disabled={runMutation.isPending || isRunInProgress}
          className="mt-2 flex items-center justify-center gap-2 rounded-lg bg-emerald-600 px-4 py-3 text-sm font-semibold text-white shadow-sm transition hover:bg-emerald-700 disabled:cursor-not-allowed disabled:opacity-60"
        >
          {runMutation.isPending || isRunInProgress ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <Play className="h-4 w-4" />
          )}
          {isRunInProgress ? `Simulation ${runStatusQuery.data?.status.toLowerCase()}…` : 'Run Simulation'}
        </button>
        {runMutation.isError && (
          <p className="text-xs text-red-600">{(runMutation.error as Error).message}</p>
        )}
        {runStatusQuery.data?.status === 'FAILED' && (
          <p className="text-xs text-red-600">Run failed: {runStatusQuery.data.error_detail}</p>
        )}
      </section>

      {/* RIGHT: results & visuals */}
      <section className="flex flex-col gap-6 lg:col-span-2">
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
          <KpiCard
            icon={<IndianRupee className="h-5 w-5 text-emerald-600" />}
            label="10-Year Total Cost"
            value={series.length ? formatCrores(totalCostInr) : '—'}
          />
          <KpiCard
            icon={<TrendingUp className="h-5 w-5 text-sky-600" />}
            label="Average Coverage"
            value={series.length ? `${avgCoveragePct.toFixed(1)}%` : '—'}
          />
          <KpiCard
            icon={<Recycle className="h-5 w-5 text-amber-600" />}
            label="Landfill Diversion Rate"
            value={series.length ? `${diversionRatePct.toFixed(1)}%` : '—'}
          />
        </div>

        <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
          <h2 className="mb-4 text-sm font-semibold uppercase tracking-wide text-slate-500">
            10-Year Trajectory — Cost vs. Landfill Remaining
          </h2>
          {resultsQuery.isLoading && activeRunId && isRunCompleted && (
            <div className="flex h-80 items-center justify-center text-sm text-slate-400">Loading results…</div>
          )}
          {!activeRunId && (
            <div className="flex h-80 items-center justify-center text-sm text-slate-400">
              No active run yet — run a simulation to see results.
            </div>
          )}
          {activeRunId && !isRunCompleted && (
            <div className="flex h-80 items-center justify-center text-sm text-slate-400">
              {runStatusQuery.data
                ? `Run is ${runStatusQuery.data.status.toLowerCase()}…`
                : 'Loading run status…'}
            </div>
          )}
          {series.length > 0 && (
            <ResponsiveContainer width="100%" height={340}>
              <ComposedChart data={series} margin={{ top: 8, right: 16, bottom: 0, left: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                <XAxis dataKey="year_index" tickFormatter={(v) => `Yr ${v}`} stroke="#64748b" fontSize={12} />
                <YAxis
                  yAxisId="left"
                  stroke="#64748b"
                  fontSize={12}
                  tickFormatter={(v: number) => `₹${(v / 1e5).toFixed(0)}L`}
                  label={{ value: 'Cost (INR)', angle: -90, position: 'insideLeft', fontSize: 12, fill: '#64748b' }}
                />
                <YAxis
                  yAxisId="right"
                  orientation="right"
                  stroke="#64748b"
                  fontSize={12}
                  tickFormatter={(v: number) => `${(v / 1000).toFixed(0)}k`}
                  label={{
                    value: 'Landfill remaining (t)',
                    angle: 90,
                    position: 'insideRight',
                    fontSize: 12,
                    fill: '#64748b',
                  }}
                />
                <Tooltip
                  formatter={(value: number, name: string) => [
                    name === 'landfill_remaining_tonnes' ? `${value.toLocaleString('en-IN')} t` : formatInr(value),
                    name,
                  ]}
                  labelFormatter={(v) => `Year ${v}`}
                />
                <Legend />
                <Bar yAxisId="left" dataKey="opex_inr" stackId="cost" name="Opex" fill="#10b981" radius={[0, 0, 0, 0]} />
                <Bar yAxisId="left" dataKey="capex_inr" stackId="cost" name="Capex" fill="#0ea5e9" radius={[4, 4, 0, 0]} />
                <Line
                  yAxisId="right"
                  type="monotone"
                  dataKey="landfill_remaining_tonnes"
                  name="Landfill remaining"
                  stroke="#f59e0b"
                  strokeWidth={2}
                  dot={false}
                />
              </ComposedChart>
            </ResponsiveContainer>
          )}
        </div>

        <div className="flex items-center justify-between rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
          <div>
            <h2 className="text-sm font-semibold text-slate-700">Detailed Project Report</h2>
            <p className="text-xs text-slate-500">Generates a PDF summary of this run's findings and yearly results.</p>
          </div>
          <button
            type="button"
            onClick={() => createReportMutation.mutate()}
            disabled={!activeRunId || !isRunCompleted || createReportMutation.isPending || isReportGenerating}
            className="flex items-center gap-2 rounded-lg bg-slate-900 px-4 py-2.5 text-sm font-medium text-white transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {createReportMutation.isPending || isReportGenerating ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Download className="h-4 w-4" />
            )}
            {isReportGenerating ? 'Generating DPR…' : 'Download DPR (PDF)'}
          </button>
        </div>
      </section>
    </div>
  )
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
