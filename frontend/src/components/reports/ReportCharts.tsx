import { useQuery } from '@tanstack/react-query'
import { Loader2, Lock } from 'lucide-react'
import { useMemo } from 'react'
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Line,
  LineChart,
  Pie,
  PieChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import {
  fetchBudgetLines,
  fetchSimulationFindings,
  fetchSimulationMonthlyResults,
  fetchSimulationResults,
} from '../../api/endpoints'
import { useCurrentUser } from '../../hooks/useCurrentUser'

const MILESTONE_FINDINGS: { code: string; label: string; colour: string }[] = [
  { code: 'LANDFILL_EXHAUSTION_YEAR', label: 'Landfill exhausted', colour: '#dc2626' },
  { code: 'TREATMENT_SATURATION_YEAR', label: 'Treatment saturated', colour: '#f59e0b' },
]

const FRACTION_COLOURS: Record<string, string> = {
  organic: '#16a34a',
  plastic: '#0ea5e9',
  paper: '#f59e0b',
  metal: '#64748b',
  glass: '#06b6d4',
  textile: '#a855f7',
  inert: '#78716c',
  ewaste: '#ef4444',
  other: '#eab308',
}
const FRACTIONS = Object.keys(FRACTION_COLOURS)

function ChartCard({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
      <h3 className="mb-3 text-xs font-semibold uppercase tracking-wide text-slate-500">{title}</h3>
      {children}
    </div>
  )
}

function ChartLoading() {
  return (
    <div className="flex h-72 items-center justify-center">
      <Loader2 className="h-5 w-5 animate-spin text-slate-400" />
    </div>
  )
}

/** 20-year line graph: Annual Waste Generated vs. Landfill Accumulation
 * (cumulative) vs. Diversion Rate. The first two share a tonnes axis;
 * diversion rate (a %) rides a second right-hand axis. */
export function TrajectoryChart({ runId }: { runId: string }) {
  const resultsQuery = useQuery({
    queryKey: ['simulation-results', runId, 'yearly'],
    queryFn: () => fetchSimulationResults(runId),
  })
  const findingsQuery = useQuery({
    queryKey: ['findings', runId],
    queryFn: () => fetchSimulationFindings(runId),
  })
  const milestones = MILESTONE_FINDINGS.map((m) => ({
    ...m,
    year: (findingsQuery.data ?? []).find((f) => f.code === m.code)?.year_index,
  })).filter((m): m is typeof m & { year: number } => m.year != null)

  const data = useMemo(() => {
    const rows: { year: number; generated_tpy: number; landfill_cumulative_tpy: number; diversion_rate_pct: number }[] = []
    for (const row of resultsQuery.data?.series ?? []) {
      const priorCumulative = rows[rows.length - 1]?.landfill_cumulative_tpy ?? 0
      rows.push({
        year: row.year_index,
        generated_tpy: row.waste_total_tpy,
        landfill_cumulative_tpy: priorCumulative + row.landfilled_tpy,
        diversion_rate_pct: row.recovery_rate_pct,
      })
    }
    return rows
  }, [resultsQuery.data])

  return (
    <ChartCard title="20-Year Trajectory — Generation vs. Landfill Accumulation vs. Diversion Rate">
      {resultsQuery.isLoading ? (
        <ChartLoading />
      ) : (
        <ResponsiveContainer width="100%" height={300}>
          <LineChart data={data} margin={{ top: 8, right: 24, bottom: 0, left: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
            <XAxis dataKey="year" tickFormatter={(v) => `Yr ${v}`} stroke="#64748b" fontSize={12} />
            <YAxis yAxisId="tonnes" stroke="#64748b" fontSize={12} />
            <YAxis yAxisId="pct" orientation="right" domain={[0, 100]} stroke="#64748b" fontSize={12} />
            <Tooltip labelFormatter={(v) => `Year ${v}`} />
            <Legend />
            {milestones.map((m) => (
              <ReferenceLine
                key={m.code}
                yAxisId="tonnes"
                x={m.year}
                stroke={m.colour}
                strokeDasharray="4 4"
                label={{ value: m.label, position: 'top', fill: m.colour, fontSize: 10 }}
              />
            ))}
            <Line
              yAxisId="tonnes"
              type="monotone"
              dataKey="generated_tpy"
              name="Annual Waste Generated (t/yr)"
              stroke="#0ea5e9"
              strokeWidth={2}
              dot={false}
            />
            <Line
              yAxisId="tonnes"
              type="monotone"
              dataKey="landfill_cumulative_tpy"
              name="Landfill Accumulation (cumulative t)"
              stroke="#dc2626"
              strokeWidth={2}
              dot={false}
            />
            <Line
              yAxisId="pct"
              type="monotone"
              dataKey="diversion_rate_pct"
              name="Diversion Rate (%)"
              stroke="#16a34a"
              strokeWidth={2}
              dot={false}
            />
          </LineChart>
        </ResponsiveContainer>
      )}
    </ChartCard>
  )
}

/** Donut of the nine canonical waste fractions. Composition is fixed by the
 * waste baseline and the engine doesn't drift it year to year (simulation_
 * yearly doesn't even carry per-fraction columns), so the most recent
 * monthly row's percentages represent the whole run. */
export function CompositionBreakdownChart({ runId }: { runId: string }) {
  const monthlyQuery = useQuery({
    queryKey: ['simulation-results', runId, 'monthly'],
    queryFn: () => fetchSimulationMonthlyResults(runId),
  })

  const data = useMemo(() => {
    const rows = monthlyQuery.data?.series ?? []
    const latest = rows[rows.length - 1]
    if (!latest) return []
    return FRACTIONS.map((fraction) => ({
      fraction,
      pct: Number(latest[`${fraction}_pct` as keyof typeof latest]),
    })).filter((row) => row.pct > 0)
  }, [monthlyQuery.data])

  return (
    <ChartCard title="Waste Composition Breakdown (9 Fractions)">
      {monthlyQuery.isLoading ? (
        <ChartLoading />
      ) : (
        <ResponsiveContainer width="100%" height={300}>
          <PieChart>
            <Pie
              data={data}
              dataKey="pct"
              nameKey="fraction"
              innerRadius={60}
              outerRadius={110}
              paddingAngle={1}
              label={(entry) => `${entry.name} ${Number(entry.value).toFixed(0)}%`}
            >
              {data.map((row) => (
                <Cell key={row.fraction} fill={FRACTION_COLOURS[row.fraction] ?? '#94a3b8'} />
              ))}
            </Pie>
            <Tooltip formatter={(value, name) => [`${Number(value).toFixed(1)}%`, name]} />
            <Legend />
          </PieChart>
        </ResponsiveContainer>
      )}
    </ChartCard>
  )
}

/** Cumulative 20-year Capex vs. Opex cost curve — gated to PLANNER/
 * RESEARCHER/ADMIN, masked for VIEWER (app/budget/router.py already nulls
 * out the equivalent summary fields for that role; the line-item detail
 * this chart needs isn't safely maskable per-row, so it's hidden outright,
 * same pattern as SimulationPage's BudgetTab). */
export function FinancialOverviewChart({ runId }: { runId: string }) {
  const { isViewer } = useCurrentUser()

  const linesQuery = useQuery({
    queryKey: ['budget-lines', runId],
    queryFn: () => fetchBudgetLines(runId),
    enabled: !isViewer,
  })

  const data = useMemo(() => {
    const lines = linesQuery.data ?? []
    const byYear = new Map<number, { year: number; capex_cumulative_inr: number; opex_cumulative_inr: number }>()
    for (const line of [...lines].sort((a, b) => a.year_index - b.year_index)) {
      const prior = byYear.get(line.year_index - 1)
      const row = byYear.get(line.year_index) ?? {
        year: line.year_index,
        capex_cumulative_inr: prior?.capex_cumulative_inr ?? 0,
        opex_cumulative_inr: prior?.opex_cumulative_inr ?? 0,
      }
      if (line.kind === 'CAPEX') row.capex_cumulative_inr += line.amount_inr
      else row.opex_cumulative_inr += line.amount_inr
      byYear.set(line.year_index, row)
    }
    return [...byYear.values()].sort((a, b) => a.year - b.year)
  }, [linesQuery.data])

  if (isViewer) {
    return (
      <ChartCard title="Financial Overview — Cumulative Capex vs. Opex">
        <div className="flex flex-col items-center gap-2 py-10 text-center">
          <Lock className="h-5 w-5 text-slate-400" />
          <p className="text-sm font-medium text-slate-600">🔒 Researcher Access Required</p>
          <p className="max-w-sm text-xs text-slate-400">
            Cost curves are restricted to Researcher accounts and above. Apply for Researcher access from the top
            navbar to view them.
          </p>
        </div>
      </ChartCard>
    )
  }

  return (
    <ChartCard title="Financial Overview — Cumulative Capex vs. Opex (20-Year)">
      {linesQuery.isLoading ? (
        <ChartLoading />
      ) : (
        <ResponsiveContainer width="100%" height={300}>
          <BarChart data={data} margin={{ top: 8, right: 16, bottom: 0, left: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
            <XAxis dataKey="year" tickFormatter={(v) => `Yr ${v}`} stroke="#64748b" fontSize={12} />
            <YAxis stroke="#64748b" fontSize={12} tickFormatter={(v) => `₹${(v / 1e5).toFixed(0)}L`} />
            <Tooltip
              labelFormatter={(v) => `Year ${v}`}
              formatter={(value) => `₹${Number(value).toLocaleString('en-IN', { maximumFractionDigits: 0 })}`}
            />
            <Legend />
            <Bar dataKey="capex_cumulative_inr" name="Cumulative Capex" stackId="cost" fill="#0ea5e9" />
            <Bar dataKey="opex_cumulative_inr" name="Cumulative Opex" stackId="cost" fill="#f59e0b" />
          </BarChart>
        </ResponsiveContainer>
      )}
    </ChartCard>
  )
}
