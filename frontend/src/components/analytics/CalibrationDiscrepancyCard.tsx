import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowRight, Loader2, TrendingUp } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import {
  createParameterSet,
  fetchHabitation,
  fetchParameterSet,
  fetchRecalibrationReport,
  upsertWasteBaseline,
} from '../../api/endpoints'
import { setDraftPsid } from '../../lib/history'
import { useCurrentUser } from '../../hooks/useCurrentUser'

export default function CalibrationDiscrepancyCard({ habitationId }: { habitationId: string }) {
  const { isReadOnly } = useCurrentUser()
  const navigate = useNavigate()
  const queryClient = useQueryClient()

  const reportQuery = useQuery({
    queryKey: ['recalibration-report', habitationId],
    queryFn: () => fetchRecalibrationReport(habitationId),
    retry: false,
  })

  const applyMutation = useMutation({
    mutationFn: async (empiricalPerCapita: number) => {
      const habitation = await fetchHabitation(habitationId)
      if (!habitation.active_parameter_set_id) throw new Error('No active parameter set to clone from')
      const active = await fetchParameterSet(habitation.active_parameter_set_id)
      const draft = await createParameterSet(habitationId, active.version_no)
      await upsertWasteBaseline(draft.id, { per_capita_generation_kg_day: empiricalPerCapita })
      return draft.id
    },
    onSuccess: (draftId) => {
      setDraftPsid(habitationId, draftId)
      queryClient.invalidateQueries({ queryKey: ['parameter-set', draftId] })
      navigate('/parameters')
    },
  })

  // A 409 means the habitation isn't READY/committed yet — nothing to
  // compare against, not an error worth surfacing as a card.
  if (reportQuery.isError || !reportQuery.data) return null

  const { total_generation_variance, per_capita_variance } = reportQuery.data
  if (total_generation_variance.theoretical === null || total_generation_variance.empirical === null) return null
  if (Math.abs(total_generation_variance.variance_pct ?? 0) < 3) return null // not worth flagging noise

  const sign = (total_generation_variance.variance_pct ?? 0) >= 0 ? '+' : ''

  return (
    <div className="flex items-start gap-3 rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm shadow-sm">
      <TrendingUp className="mt-0.5 h-5 w-5 shrink-0 text-amber-600" />
      <div className="flex-1">
        <p className="font-medium text-amber-900">
          Your theoretical baseline assumes {total_generation_variance.theoretical.toFixed(2)} t/day, but the
          last 30-day average is {total_generation_variance.empirical.toFixed(2)} t/day (
          {sign}
          {(total_generation_variance.variance_pct ?? 0).toFixed(1)}%).
        </p>
        <p className="mt-0.5 text-xs text-amber-700">
          Based on {reportQuery.data.logged_day_count_90d} logged day(s) in the last 90.
        </p>
        {!isReadOnly && per_capita_variance.empirical !== null && (
          <button
            type="button"
            onClick={() => applyMutation.mutate(per_capita_variance.empirical as number)}
            disabled={applyMutation.isPending}
            className="mt-2 flex items-center gap-1.5 rounded-lg border border-amber-300 bg-white px-3 py-1.5 text-xs font-medium text-amber-800 transition hover:bg-amber-100 disabled:opacity-60"
          >
            {applyMutation.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <ArrowRight className="h-3.5 w-3.5" />}
            Click to update draft parameters
          </button>
        )}
        {applyMutation.isError && (
          <p className="mt-1 text-xs text-red-600">{(applyMutation.error as Error).message}</p>
        )}
      </div>
    </div>
  )
}
