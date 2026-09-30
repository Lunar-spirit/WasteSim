import { useQuery } from '@tanstack/react-query'
import { Loader2 } from 'lucide-react'
import { fetchSimulationFindings, fetchSimulationMonthlyResults } from '../../api/endpoints'
import type { SimulationMonthly, SimulationYearly } from '../../types/api'
import BudgetVsCumulativeChart from './BudgetVsCumulativeChart'
import EnvironmentalImpactChart from './EnvironmentalImpactChart'
import LandfillLifespanChart from './LandfillLifespanChart'
import WasteBreakdownChart, { type WasteBreakdownYear } from './WasteBreakdownChart'

// Each year's tonnage is exact (straight from simulation_yearly.waste_total_tpy);
// only the organic/plastic/paper *split* is approximated as that year's average
// monthly composition — composition drifts slowly and doesn't need day-exact
// weighting for a chart. "Inert" is the residual, not its own average, so the
// four series always stack back to the exact yearly total with no rounding gap.
function computeWasteBreakdown(yearly: SimulationYearly[], monthly: SimulationMonthly[]): WasteBreakdownYear[] {
  const monthsByYear = new Map<number, SimulationMonthly[]>()
  for (const m of monthly) {
    const arr = monthsByYear.get(m.year_index) ?? []
    arr.push(m)
    monthsByYear.set(m.year_index, arr)
  }
  const avgPct = (months: SimulationMonthly[], key: 'organic_pct' | 'plastic_pct' | 'paper_pct') =>
    months.length ? months.reduce((sum, m) => sum + m[key], 0) / months.length : 0

  return yearly.map((y) => {
    const months = monthsByYear.get(y.year_index) ?? []
    const organic = (y.waste_total_tpy * avgPct(months, 'organic_pct')) / 100
    const plastic = (y.waste_total_tpy * avgPct(months, 'plastic_pct')) / 100
    const paper = (y.waste_total_tpy * avgPct(months, 'paper_pct')) / 100
    const inert = Math.max(0, y.waste_total_tpy - organic - plastic - paper)
    return { year_index: y.year_index, organic, plastic, paper, inert }
  })
}

export default function AnalyticsTab({
  runId,
  series,
  annualBudgetInr,
}: {
  runId: string | null
  series: SimulationYearly[]
  annualBudgetInr: number
}) {
  const monthlyQuery = useQuery({
    queryKey: ['simulation-monthly', runId],
    queryFn: () => fetchSimulationMonthlyResults(runId as string),
    enabled: !!runId,
  })
  const findingsQuery = useQuery({
    queryKey: ['findings', runId],
    queryFn: () => fetchSimulationFindings(runId as string),
    enabled: !!runId,
  })

  if (!runId) {
    return (
      <div className="rounded-xl border border-slate-200 bg-white p-8 text-center text-sm text-slate-400">
        Run a simulation first.
      </div>
    )
  }
  if (monthlyQuery.isLoading || findingsQuery.isLoading) {
    return (
      <div className="flex justify-center p-8">
        <Loader2 className="h-5 w-5 animate-spin text-slate-400" />
      </div>
    )
  }

  const monthly = monthlyQuery.data?.series ?? []
  const breakdown = computeWasteBreakdown(series, monthly)
  const exhaustionFinding = (findingsQuery.data ?? []).find((f) => f.code === 'LANDFILL_EXHAUSTION_YEAR')
  const exhaustionYear = exhaustionFinding?.year_index ?? null

  return (
    <div className="grid grid-cols-1 gap-5 xl:grid-cols-2">
      <WasteBreakdownChart data={breakdown} />
      <BudgetVsCumulativeChart series={series} annualBudgetInr={annualBudgetInr} />
      <LandfillLifespanChart series={series} exhaustionYear={exhaustionYear} />
      <EnvironmentalImpactChart series={series} />
    </div>
  )
}
