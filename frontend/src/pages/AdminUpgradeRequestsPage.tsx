import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Check, Loader2, Trash2, X } from 'lucide-react'
import { useState } from 'react'
import {
  assignUserRole,
  fetchAllUsers,
  fetchHabitationMembers,
  fetchHabitations,
  fetchUpgradeRequests,
  grantHabitationAccess,
  revokeHabitationAccess,
  reviewUpgradeRequest,
} from '../api/endpoints'
import type { AccessLevel, CurrentUser, RoleUpgradeRequestAdmin, RoleUpgradeRequestStatus, UserRole } from '../types/api'

const STATUS_TABS: RoleUpgradeRequestStatus[] = ['PENDING', 'APPROVED', 'REJECTED']
const ALL_ROLES: UserRole[] = ['VIEWER', 'RESEARCHER', 'PLANNER', 'ADMIN']
const ALL_ACCESS_LEVELS: AccessLevel[] = ['VIEWER', 'EDITOR', 'OWNER']

function ReviewButtons({ request }: { request: RoleUpgradeRequestAdmin }) {
  const queryClient = useQueryClient()
  const [notes, setNotes] = useState('')
  const [showRejectNotes, setShowRejectNotes] = useState(false)

  const reviewMutation = useMutation({
    mutationFn: (action: 'APPROVE' | 'REJECT') =>
      reviewUpgradeRequest(request.id, { action, review_notes: notes.trim() || undefined }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['upgradeRequests'] }),
  })

  if (showRejectNotes) {
    return (
      <div className="flex flex-col gap-1.5">
        <textarea
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          placeholder="Rejection reason (optional)…"
          rows={2}
          className="w-48 rounded-md border border-slate-300 px-2 py-1 text-xs focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500"
        />
        <div className="flex gap-1.5">
          <button
            type="button"
            onClick={() => reviewMutation.mutate('REJECT')}
            disabled={reviewMutation.isPending}
            className="flex items-center gap-1 rounded-md bg-red-600 px-2.5 py-1 text-xs font-medium text-white transition hover:bg-red-700 disabled:opacity-60"
          >
            {reviewMutation.isPending && <Loader2 className="h-3 w-3 animate-spin" />}
            Confirm Reject
          </button>
          <button
            type="button"
            onClick={() => setShowRejectNotes(false)}
            className="rounded-md border border-slate-300 px-2.5 py-1 text-xs text-slate-600 hover:bg-slate-50"
          >
            Cancel
          </button>
        </div>
      </div>
    )
  }

  return (
    <div className="flex items-center gap-1.5">
      <button
        type="button"
        onClick={() => reviewMutation.mutate('APPROVE')}
        disabled={reviewMutation.isPending}
        className="flex items-center gap-1 rounded-md bg-emerald-600 px-2.5 py-1 text-xs font-medium text-white transition hover:bg-emerald-700 disabled:opacity-60"
      >
        <Check className="h-3 w-3" />
        Approve
      </button>
      <button
        type="button"
        onClick={() => setShowRejectNotes(true)}
        disabled={reviewMutation.isPending}
        className="flex items-center gap-1 rounded-md border border-red-300 px-2.5 py-1 text-xs font-medium text-red-600 transition hover:bg-red-50 disabled:opacity-60"
      >
        <X className="h-3 w-3" />
        Reject
      </button>
    </div>
  )
}

function UserRoleRow({ user }: { user: CurrentUser }) {
  const queryClient = useQueryClient()
  const [pendingRole, setPendingRole] = useState<UserRole | null>(null)

  const assignMutation = useMutation({
    mutationFn: (role: UserRole) => assignUserRole(user.id, role),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['allUsers'] })
      queryClient.invalidateQueries({ queryKey: ['currentUser'] })
      setPendingRole(null)
    },
  })

  return (
    <tr className="border-b border-slate-50 last:border-0">
      <td className="px-5 py-3">
        <p className="font-medium text-slate-800">{user.full_name}</p>
        <p className="text-xs text-slate-400">{user.email}</p>
      </td>
      <td className="px-3 py-3 whitespace-nowrap text-slate-500">{new Date(user.created_at).toLocaleDateString()}</td>
      <td className="px-3 py-3">
        <div className="flex items-center gap-2">
          <select
            value={pendingRole ?? user.role}
            onChange={(e) => setPendingRole(e.target.value as UserRole)}
            className="rounded-md border border-slate-300 bg-white px-2 py-1 text-xs focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500"
          >
            {ALL_ROLES.map((r) => (
              <option key={r} value={r}>
                {r}
              </option>
            ))}
          </select>
          {pendingRole !== null && pendingRole !== user.role && (
            <button
              type="button"
              onClick={() => assignMutation.mutate(pendingRole)}
              disabled={assignMutation.isPending}
              className="flex items-center gap-1 rounded-md bg-emerald-600 px-2.5 py-1 text-xs font-medium text-white transition hover:bg-emerald-700 disabled:opacity-60"
            >
              {assignMutation.isPending && <Loader2 className="h-3 w-3 animate-spin" />}
              Save
            </button>
          )}
        </div>
        {assignMutation.isError && (
          <p className="mt-1 text-xs text-red-600">{(assignMutation.error as Error).message}</p>
        )}
      </td>
    </tr>
  )
}

function ManageUsersTab() {
  const usersQuery = useQuery({ queryKey: ['allUsers'], queryFn: fetchAllUsers })
  const users = usersQuery.data ?? []

  return (
    <div className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
      {usersQuery.isLoading && (
        <div className="flex justify-center p-8">
          <Loader2 className="h-5 w-5 animate-spin text-slate-400" />
        </div>
      )}
      {!usersQuery.isLoading && users.length > 0 && (
        <table className="w-full text-left text-sm">
          <thead>
            <tr className="border-b border-slate-200 text-xs uppercase tracking-wide text-slate-400">
              <th className="px-5 py-2.5">User</th>
              <th className="px-3 py-2.5">Joined</th>
              <th className="px-3 py-2.5">Role</th>
            </tr>
          </thead>
          <tbody>
            {users.map((u) => (
              <UserRoleRow key={u.id} user={u} />
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}

function GrantAccessForm({ habitationId }: { habitationId: string }) {
  const queryClient = useQueryClient()
  const [email, setEmail] = useState('')
  const [accessLevel, setAccessLevel] = useState<AccessLevel>('VIEWER')

  const grantMutation = useMutation({
    mutationFn: () => grantHabitationAccess(habitationId, { email, access_level: accessLevel }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['habitationMembers', habitationId] })
      setEmail('')
    },
  })

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault()
        grantMutation.mutate()
      }}
      className="flex flex-wrap items-end gap-2 border-b border-slate-200 bg-slate-50 p-4"
    >
      <label className="flex flex-col gap-1 text-xs">
        <span className="font-medium text-slate-600">User email</span>
        <input
          type="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          placeholder="user@example.com"
          required
          className="w-56 rounded-md border border-slate-300 px-2.5 py-1.5 text-sm focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500"
        />
      </label>
      <label className="flex flex-col gap-1 text-xs">
        <span className="font-medium text-slate-600">Access level</span>
        <select
          value={accessLevel}
          onChange={(e) => setAccessLevel(e.target.value as AccessLevel)}
          className="rounded-md border border-slate-300 bg-white px-2.5 py-1.5 text-sm focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500"
        >
          {ALL_ACCESS_LEVELS.map((level) => (
            <option key={level} value={level}>
              {level}
            </option>
          ))}
        </select>
      </label>
      <button
        type="submit"
        disabled={grantMutation.isPending}
        className="flex items-center gap-1.5 rounded-lg bg-emerald-600 px-3.5 py-2 text-sm font-medium text-white transition hover:bg-emerald-700 disabled:opacity-60"
      >
        {grantMutation.isPending && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
        Grant Access
      </button>
      {grantMutation.isError && (
        <p className="w-full text-xs text-red-600">{(grantMutation.error as Error).message}</p>
      )}
    </form>
  )
}

function HabitationAccessTab() {
  const habitationsQuery = useQuery({ queryKey: ['habitations'], queryFn: fetchHabitations })
  const habitations = habitationsQuery.data ?? []
  const [habitationId, setHabitationId] = useState<string>('')
  const effectiveId = habitationId || habitations[0]?.id || ''

  const queryClient = useQueryClient()
  const membersQuery = useQuery({
    queryKey: ['habitationMembers', effectiveId],
    queryFn: () => fetchHabitationMembers(effectiveId),
    enabled: !!effectiveId,
  })
  const members = membersQuery.data ?? []

  const revokeMutation = useMutation({
    mutationFn: (memberId: string) => revokeHabitationAccess(effectiveId, memberId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['habitationMembers', effectiveId] }),
  })

  return (
    <div className="flex flex-col gap-3">
      <label className="flex items-center gap-2 text-sm">
        <span className="text-slate-500">Habitation</span>
        <select
          value={effectiveId}
          onChange={(e) => setHabitationId(e.target.value)}
          className="rounded-md border border-slate-300 bg-white px-2.5 py-1.5 text-sm focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500"
        >
          {habitations.map((h) => (
            <option key={h.id} value={h.id}>
              {h.name} ({h.status})
            </option>
          ))}
        </select>
      </label>

      {effectiveId && (
        <div className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
          <GrantAccessForm habitationId={effectiveId} />
          {membersQuery.isLoading && (
            <div className="flex justify-center p-8">
              <Loader2 className="h-5 w-5 animate-spin text-slate-400" />
            </div>
          )}
          {!membersQuery.isLoading && members.length === 0 && (
            <p className="p-6 text-sm text-slate-400">No members granted access yet.</p>
          )}
          {members.length > 0 && (
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="border-b border-slate-200 text-xs uppercase tracking-wide text-slate-400">
                  <th className="px-5 py-2.5">User</th>
                  <th className="px-3 py-2.5">Access Level</th>
                  <th className="px-3 py-2.5">Granted</th>
                  <th className="px-3 py-2.5">Action</th>
                </tr>
              </thead>
              <tbody>
                {members.map((m) => (
                  <tr key={m.id} className="border-b border-slate-50 last:border-0">
                    <td className="px-5 py-3">
                      <p className="font-medium text-slate-800">{m.user_full_name}</p>
                      <p className="text-xs text-slate-400">{m.user_email}</p>
                    </td>
                    <td className="px-3 py-3 text-slate-600">{m.access_level}</td>
                    <td className="px-3 py-3 whitespace-nowrap text-slate-500">
                      {new Date(m.created_at).toLocaleDateString()}
                    </td>
                    <td className="px-3 py-3">
                      <button
                        type="button"
                        onClick={() => revokeMutation.mutate(m.id)}
                        disabled={revokeMutation.isPending}
                        className="flex items-center gap-1 rounded-md border border-red-300 px-2.5 py-1 text-xs font-medium text-red-600 transition hover:bg-red-50 disabled:opacity-60"
                      >
                        <Trash2 className="h-3 w-3" />
                        Revoke
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
    </div>
  )
}

export default function AdminUpgradeRequestsPage() {
  const [tab, setTab] = useState<'requests' | 'users' | 'access'>('requests')
  const [statusFilter, setStatusFilter] = useState<RoleUpgradeRequestStatus>('PENDING')

  const requestsQuery = useQuery({
    queryKey: ['upgradeRequests', statusFilter],
    queryFn: () => fetchUpgradeRequests(statusFilter),
    enabled: tab === 'requests',
  })
  const requests = requestsQuery.data ?? []

  return (
    <div className="flex flex-col gap-4 p-6">
      <div>
        <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500">Access Management</h2>
        <p className="mt-1 text-sm text-slate-500">
          Review Researcher applications, assign global roles, or grant per-habitation access.
        </p>
      </div>

      <div className="flex gap-1.5 border-b border-slate-200 pb-2">
        <button
          type="button"
          onClick={() => setTab('requests')}
          className={`rounded-md px-3 py-1.5 text-xs font-medium transition ${
            tab === 'requests' ? 'bg-slate-900 text-white' : 'bg-slate-100 text-slate-600 hover:bg-slate-200'
          }`}
        >
          Upgrade Requests
        </button>
        <button
          type="button"
          onClick={() => setTab('users')}
          className={`rounded-md px-3 py-1.5 text-xs font-medium transition ${
            tab === 'users' ? 'bg-slate-900 text-white' : 'bg-slate-100 text-slate-600 hover:bg-slate-200'
          }`}
        >
          Manage Users
        </button>
        <button
          type="button"
          onClick={() => setTab('access')}
          className={`rounded-md px-3 py-1.5 text-xs font-medium transition ${
            tab === 'access' ? 'bg-slate-900 text-white' : 'bg-slate-100 text-slate-600 hover:bg-slate-200'
          }`}
        >
          Habitation Access
        </button>
      </div>

      {tab === 'users' && <ManageUsersTab />}
      {tab === 'access' && <HabitationAccessTab />}

      {tab === 'requests' && (
        <>
          <div className="flex gap-1.5">
            {STATUS_TABS.map((s) => (
              <button
                key={s}
                type="button"
                onClick={() => setStatusFilter(s)}
                className={`rounded-md px-3 py-1.5 text-xs font-medium transition ${
                  statusFilter === s ? 'bg-slate-900 text-white' : 'bg-slate-100 text-slate-600 hover:bg-slate-200'
                }`}
              >
                {s}
              </button>
            ))}
          </div>

          <div className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
            {requestsQuery.isLoading && (
              <div className="flex justify-center p-8">
                <Loader2 className="h-5 w-5 animate-spin text-slate-400" />
              </div>
            )}
            {!requestsQuery.isLoading && requests.length === 0 && (
              <p className="p-6 text-sm text-slate-400">No {statusFilter.toLowerCase()} applications.</p>
            )}
            {requests.length > 0 && (
              <table className="w-full text-left text-sm">
                <thead>
                  <tr className="border-b border-slate-200 text-xs uppercase tracking-wide text-slate-400">
                    <th className="px-5 py-2.5">Applicant</th>
                    <th className="px-3 py-2.5">Institution</th>
                    <th className="px-3 py-2.5">Reason</th>
                    <th className="px-3 py-2.5">Applied</th>
                    {statusFilter === 'PENDING' && <th className="px-3 py-2.5">Action</th>}
                  </tr>
                </thead>
                <tbody>
                  {requests.map((r) => (
                    <tr key={r.id} className="border-b border-slate-50 last:border-0 align-top">
                      <td className="px-5 py-3">
                        <p className="font-medium text-slate-800">{r.applicant_full_name}</p>
                        <p className="text-xs text-slate-400">{r.applicant_email}</p>
                      </td>
                      <td className="px-3 py-3 text-slate-600">{r.institution_or_department ?? '—'}</td>
                      <td className="max-w-xs px-3 py-3 text-slate-600">{r.reason}</td>
                      <td className="px-3 py-3 whitespace-nowrap text-slate-500">
                        {new Date(r.created_at).toLocaleDateString()}
                      </td>
                      {statusFilter === 'PENDING' && (
                        <td className="px-3 py-3">
                          <ReviewButtons request={r} />
                        </td>
                      )}
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </>
      )}
    </div>
  )
}
