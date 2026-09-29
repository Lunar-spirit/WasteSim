import { useMemo, useState } from 'react'
import { Clock, IndianRupee, Loader2, TrendingDown } from 'lucide-react'
import { formatCrores, formatTonnes } from '../../lib/format'
import type { ComparativePreviewResult } from '../../types/api'
import OpexComparisonChart from './OpexComparisonChart'
import WasteCollectionComparisonChart from './WasteCollectionComparisonChart'

function StatBadge({
  icon,
  label,
  value,
  tone,
}: {
  icon: React.ReactNode
  label: string
  value: string
  tone: 'amber' | 'red' | 'emerald' | 'slate'
}) {
  const toneClass = {
    amber: 'border-amber-200 bg-amber-50 text-amber-800',
    red: 'border-red-200 bg-red-50 text-red-800',
    emerald: 'border-emerald-200 bg-emerald-50 text-emerald-800',
    slate: 'border-slate-200 bg-slate-50 text-slate-700',
  }[tone]
  return (
    <div className={`flex items-center gap-3 rounded-xl border p-4 ${toneClass}`}>
      <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-white/60">{icon}</div>
      <div>
        <p className="text-[11px] font-medium uppercase tracking-wide opacity-70">{label}</p>
        <p className="text-base font-semibold">{value}</p>
      </div>
    </div>
  )
}

export default function ComparativeImpactDashboard({
  result,
  isLoading,
  error,
}: {
  result: ComparativePreviewResult | undefined
  isLoading: boolean
  error: Error | null
}) {
  const [zoom, setZoom] = useState<'shock' | 'full'>('shock')

  const eventEndMonth = result ? result.start_month + result.duration_months - 1 : 0

  const visibleSeries = useMemo(() => {
    if (!result) return []
    if (zoom === 'full') return result.series
    const windowStart = Math.max(1, result.start_month - 2)
    const windowEnd = Math.min(result.horizon_months, result.start_month + 9)
    return result.series.filter((row) => row.month >= windowStart && row.month <= windowEnd)
  }, [result, zoom])

  return (
    <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold uppercase tracking-wide text-slate-500">Comparative Impact Dashboard</h3>
          <p className="mt-0.5 text-xs text-slate-400">
            Instant base-vs-shocked projection — computed live, nothing here is a saved run.
          </p>
        </div>
        {result && (
          <div className="flex items-center gap-1 rounded-lg bg-slate-100 p-1 text-xs font-medium">
            <button
              type="button"
              onClick={() => setZoom('shock')}
              className={`rounded-md px-2.5 py-1 transition ${zoom === 'shock' ? 'bg-white text-slate-900 shadow-sm' : 'text-slate-500'}`}
            >
              12-month zoom
            </button>
            <button
              type="button"
              onClick={() => setZoom('full')}
              className={`rounded-md px-2.5 py-1 transition ${zoom === 'full' ? 'bg-white text-slate-900 shadow-sm' : 'text-slate-500'}`}
            >
              Full horizon ({result.horizon_months} mo)
            </button>
          </div>
        )}
      </div>

      {isLoading && (
        <div className="flex h-48 items-center justify-center gap-2 text-sm text-slate-400">
          <Loader2 className="h-5 w-5 animate-spin" />
          Running base and scenario projections…
        </div>
      )}
      {error && !isLoading && (
        <p className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">{error.message}</p>
      )}
      {!result && !isLoading && !error && (
        <p className="flex h-32 items-center justify-center text-sm text-slate-400">
          Click "Preview Impact" or "Run Full Scenario" above to see the comparison instantly.
        </p>
      )}

      {result && !isLoading && (
        <div className="flex flex-col gap-5">
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <StatBadge
              icon={<TrendingDown className="h-4 w-4" />}
              label="Peak Backlog Waste"
              value={formatTonnes(result.peak_backlog_tonnes)}
              tone="amber"
            />
            <StatBadge
              icon={<IndianRupee className="h-4 w-4" />}
              label="Net Financial Penalty"
              value={`${result.net_financial_penalty_inr >= 0 ? '+' : ''}${formatCrores(result.net_financial_penalty_inr)}`}
              tone={result.net_financial_penalty_inr >= 0 ? 'red' : 'emerald'}
            />
            <StatBadge
              icon={<Clock className="h-4 w-4" />}
              label="Recovery Time"
              value={result.recovery_time_weeks !== null ? `${result.recovery_time_weeks.toFixed(1)} wks` : 'Beyond horizon'}
              tone="slate"
            />
          </div>

          <WasteCollectionComparisonChart series={visibleSeries} startMonth={result.start_month} endMonth={eventEndMonth} />
          <OpexComparisonChart series={visibleSeries} startMonth={result.start_month} endMonth={eventEndMonth} />

          {result.notes.length > 0 && (
            <ul className="flex flex-col gap-1 rounded-lg bg-slate-50 p-3 text-[11px] text-slate-500">
              {result.notes.map((note, idx) => (
                <li key={idx}>• {note}</li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  )
}
