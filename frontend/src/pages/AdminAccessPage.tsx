import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Loader2, Shield, ShieldOff } from 'lucide-react'
import { useState } from 'react'
import {
  assignPlanner,
  changeUserRole,
  fetchHabitations,
  fetchUsersWithAccess,
  unassignPlanner,
} from '../api/endpoints'
import type { UserRole } from '../types/api'

const ROLES: UserRole[] = ['ADMIN', 'PLANNER', 'RESEARCHER', 'POLICY_VIEWER']
const ROLE_LABELS: Record<UserRole, string> = {
  ADMIN: 'Admin',
  PLANNER: 'Planner',
  RESEARCHER: 'Researcher',
  POLICY_VIEWER: 'Viewer',
}

export default function AdminAccessPage() {
  const queryClient = useQueryClient()
  const [error, setError] = useState<string | null>(null)

  const usersQuery = useQuery({ queryKey: ['admin', 'users'], queryFn: fetchUsersWithAccess })
  const habitationsQuery = useQuery({ queryKey: ['habitations'], queryFn: fetchHabitations })

  function invalidate() {
    queryClient.invalidateQueries({ queryKey: ['admin', 'users'] })
  }

  const toggleAssignment = useMutation({
    mutationFn: async ({ userId, habitationId, assigned }: { userId: string; habitationId: string; assigned: boolean }) =>
      assigned ? unassignPlanner(userId, habitationId) : assignPlanner(userId, habitationId),
    onSuccess: invalidate,
    onError: (err: Error) => setError(err.message),
  })

  const roleMutation = useMutation({
    mutationFn: ({ userId, role }: { userId: string; role: UserRole }) => changeUserRole(userId, role),
    onSuccess: invalidate,
    onError: (err: Error) => setError(err.message),
  })

  const planners = (usersQuery.data ?? []).filter((u) => u.role === 'PLANNER')
  const habitations = habitationsQuery.data ?? []

  return (
    <div className="flex h-full flex-col gap-6 overflow-y-auto p-6">
      <div>
        <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500">Admin Access Control</h2>
        <p className="mt-1 text-sm text-slate-500">
          Manage user roles and which habitations each Planner can write to. Assigning a Planner grants write
          access (drafts, GIS layers, simulations) on that habitation only; unassigning revokes it immediately.
        </p>
      </div>

      {error && (
        <p className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">{error}</p>
      )}

      <section className="rounded-2xl border border-slate-200 bg-white p-5">
        <h3 className="mb-3 text-sm font-semibold text-slate-800">Users &amp; roles</h3>
        {usersQuery.isLoading ? (
          <Loader2 className="h-4 w-4 animate-spin text-slate-400" />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="border-b border-slate-200 text-xs uppercase tracking-wide text-slate-400">
                  <th className="py-2 pr-4">User</th>
                  <th className="py-2 pr-4">Role</th>
                  <th className="py-2 pr-4">Habitations assigned</th>
                </tr>
              </thead>
              <tbody>
                {(usersQuery.data ?? []).map((u) => (
                  <tr key={u.id} className="border-b border-slate-100 last:border-0">
                    <td className="py-2.5 pr-4">
                      <div className="font-medium text-slate-800">{u.full_name}</div>
                      <div className="text-xs text-slate-400">{u.email}</div>
                    </td>
                    <td className="py-2.5 pr-4">
                      <select
                        value={u.role}
                        disabled={roleMutation.isPending}
                        onChange={(e) => roleMutation.mutate({ userId: u.id, role: e.target.value as UserRole })}
                        className="rounded-md border border-slate-300 bg-white px-2 py-1 text-xs text-slate-700 focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500"
                      >
                        {ROLES.map((r) => (
                          <option key={r} value={r}>
                            {ROLE_LABELS[r]}
                          </option>
                        ))}
                      </select>
                    </td>
                    <td className="py-2.5 pr-4 text-xs text-slate-500">
                      {u.role === 'PLANNER' ? u.habitation_ids.length : '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="rounded-2xl border border-slate-200 bg-white p-5">
        <h3 className="mb-1 text-sm font-semibold text-slate-800">Planner ↔ Habitation assignments</h3>
        <p className="mb-3 text-xs text-slate-400">
          Click a cell to toggle a Planner's write access to that habitation. Only users with the Planner role
          appear here — change a user's role above first if they're missing.
        </p>
        {planners.length === 0 ? (
          <p className="text-sm text-slate-400">No Planner-role users yet.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="border-b border-slate-200 text-xs uppercase tracking-wide text-slate-400">
                  <th className="py-2 pr-4">Planner</th>
                  {habitations.map((h) => (
                    <th key={h.id} className="px-2 py-2 text-center font-medium">
                      {h.name}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {planners.map((p) => (
                  <tr key={p.id} className="border-b border-slate-100 last:border-0">
                    <td className="py-2.5 pr-4 font-medium text-slate-800">{p.full_name}</td>
                    {habitations.map((h) => {
                      const assigned = p.habitation_ids.includes(h.id)
                      const pending =
                        toggleAssignment.isPending &&
                        toggleAssignment.variables?.userId === p.id &&
                        toggleAssignment.variables?.habitationId === h.id
                      return (
                        <td key={h.id} className="px-2 py-2 text-center">
                          <button
                            type="button"
                            disabled={pending}
                            onClick={() =>
                              toggleAssignment.mutate({ userId: p.id, habitationId: h.id, assigned })
                            }
                            title={assigned ? 'Assigned — click to revoke' : 'Not assigned — click to grant'}
                            className={`inline-flex h-7 w-7 items-center justify-center rounded-md border transition ${
                              assigned
                                ? 'border-emerald-300 bg-emerald-50 text-emerald-600 hover:bg-emerald-100'
                                : 'border-slate-200 bg-white text-slate-300 hover:bg-slate-50'
                            } disabled:opacity-60`}
                          >
                            {pending ? (
                              <Loader2 className="h-3.5 w-3.5 animate-spin" />
                            ) : assigned ? (
                              <Shield className="h-3.5 w-3.5" />
                            ) : (
                              <ShieldOff className="h-3.5 w-3.5" />
                            )}
                          </button>
                        </td>
                      )
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  )
}
