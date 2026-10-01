import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Loader2, X } from 'lucide-react'
import { useState } from 'react'
import { applyForResearcher } from '../api/endpoints'

export default function ApplyResearcherModal({ onClose }: { onClose: () => void }) {
  const queryClient = useQueryClient()
  const [reason, setReason] = useState('')
  const [institution, setInstitution] = useState('')

  const applyMutation = useMutation({
    mutationFn: () =>
      applyForResearcher({
        reason,
        institution_or_department: institution.trim() || undefined,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['myApplicationStatus'] })
      onClose()
    },
  })

  const reasonTooShort = reason.trim().length > 0 && reason.trim().length < 20

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center bg-slate-900/40 p-4">
      <div className="w-full max-w-md rounded-2xl bg-white p-6 shadow-2xl">
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-base font-semibold text-slate-900">Apply for Researcher Role</h2>
          <button type="button" onClick={onClose} className="rounded-md p-1 text-slate-400 hover:bg-slate-100">
            <X className="h-4 w-4" />
          </button>
        </div>
        <p className="mb-4 text-sm text-slate-500">
          Researcher access unlocks cost/budget detail, draft parameters, and the ability to run scenarios. An
          admin reviews every application.
        </p>

        <form
          onSubmit={(e) => {
            e.preventDefault()
            applyMutation.mutate()
          }}
          className="flex flex-col gap-3"
        >
          <label className="flex flex-col gap-1 text-sm">
            <span className="font-medium text-slate-700">Reason / Intended Research Scope</span>
            <textarea
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              rows={4}
              minLength={20}
              required
              placeholder="e.g. Studying waste collection efficiency across coastal Karnataka for my M.Tech thesis…"
              className="rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500"
            />
            {reasonTooShort && <span className="text-xs text-amber-600">At least 20 characters.</span>}
          </label>
          <label className="flex flex-col gap-1 text-sm">
            <span className="font-medium text-slate-700">Institution / Department (optional)</span>
            <input
              type="text"
              value={institution}
              onChange={(e) => setInstitution(e.target.value)}
              placeholder="e.g. Dept. of Civil Engineering, XYZ University"
              className="rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500"
            />
          </label>

          {applyMutation.isError && (
            <p className="text-xs text-red-600">{(applyMutation.error as Error).message}</p>
          )}

          <button
            type="submit"
            disabled={reason.trim().length < 20 || applyMutation.isPending}
            className="mt-1 flex items-center justify-center gap-2 rounded-lg bg-emerald-600 px-4 py-2.5 text-sm font-semibold text-white transition hover:bg-emerald-700 disabled:opacity-60"
          >
            {applyMutation.isPending && <Loader2 className="h-4 w-4 animate-spin" />}
            Submit Application
          </button>
        </form>
      </div>
    </div>
  )
}
