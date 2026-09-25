import { useQuery } from '@tanstack/react-query'
import {
  Activity,
  CloudRain,
  FileText,
  GitCompare,
  LayoutDashboard,
  LogOut,
  Map as MapIcon,
  Plus,
  SlidersHorizontal,
  Sparkles,
  Target,
} from 'lucide-react'
import { useEffect, useState } from 'react'
import { NavLink, Outlet } from 'react-router-dom'
import { fetchHabitations } from '../api/endpoints'
import { logout } from '../api/client'
import { useAppContext } from '../context/AppContext'
import ChatDrawer from './ChatDrawer'
import CreateHabitationModal from './CreateHabitationModal'

const NAV_ITEMS = [
  { to: '/gis', label: 'GIS Studio', icon: MapIcon },
  { to: '/parameters', label: 'Parameters', icon: SlidersHorizontal },
  { to: '/simulation', label: 'Simulation & Budget', icon: LayoutDashboard },
  { to: '/scenarios', label: 'Scenarios', icon: CloudRain },
  { to: '/sensitivity', label: 'Sensitivity', icon: Activity },
  { to: '/optimization', label: 'Optimization', icon: Target },
  { to: '/comparison', label: 'Comparison', icon: GitCompare },
  { to: '/reports', label: 'Reports', icon: FileText },
]

function Header() {
  const { currentHabitationId, setCurrentHabitationId, setActiveRunId, setIsCopilotOpen } = useAppContext()
  const [isCreateOpen, setIsCreateOpen] = useState(false)

  const habitationsQuery = useQuery({
    queryKey: ['habitations'],
    queryFn: fetchHabitations,
  })

  function handleHabitationChange(id: string) {
    setCurrentHabitationId(id)
    // A run belongs to one habitation — switching habitations without a
    // known run for it means no chart to show until a new one is run.
    setActiveRunId(null)
  }

  return (
    <header className="flex flex-col border-b border-slate-200 bg-white">
      <div className="flex items-center justify-between px-6 py-3">
        <div className="flex items-center gap-6">
          <div className="flex items-center gap-2">
            <Sparkles className="h-5 w-5 text-emerald-600" />
            <span className="text-base font-bold text-slate-900">SWMS Lite</span>
          </div>

          <div className="flex items-center gap-1.5">
            <select
              value={currentHabitationId}
              onChange={(e) => handleHabitationChange(e.target.value)}
              className="rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm text-slate-700 focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500"
            >
              {habitationsQuery.isLoading && <option>Loading habitations…</option>}
              {habitationsQuery.data?.map((h) => (
                <option key={h.id} value={h.id}>
                  {h.name} ({h.status})
                </option>
              ))}
            </select>
            <button
              type="button"
              onClick={() => setIsCreateOpen(true)}
              title="New habitation"
              className="flex items-center gap-1 rounded-md border border-slate-300 px-2 py-1.5 text-sm text-slate-600 transition hover:bg-slate-50"
            >
              <Plus className="h-3.5 w-3.5" />
            </button>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => setIsCopilotOpen(true)}
            className="flex items-center gap-2 rounded-lg bg-emerald-600 px-3.5 py-2 text-sm font-medium text-white transition hover:bg-emerald-700"
            title="Cmd/Ctrl+K"
          >
            <Sparkles className="h-4 w-4" />
            Open AI Copilot
          </button>
          <button
            type="button"
            onClick={logout}
            className="flex items-center gap-1.5 rounded-lg border border-slate-200 px-3 py-2 text-sm text-slate-500 transition hover:bg-slate-50"
            title="Sign out"
          >
            <LogOut className="h-4 w-4" />
          </button>
        </div>
      </div>

      <nav className="flex items-center gap-1 overflow-x-auto px-6 pb-2">
        {NAV_ITEMS.map(({ to, label, icon: Icon }) => (
          <NavLink
            key={to}
            to={to}
            className={({ isActive }) =>
              `flex shrink-0 items-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-medium transition ${
                isActive ? 'bg-slate-900 text-white' : 'text-slate-500 hover:bg-slate-100 hover:text-slate-700'
              }`
            }
          >
            <Icon className="h-3.5 w-3.5" />
            {label}
          </NavLink>
        ))}
      </nav>

      {isCreateOpen && (
        <CreateHabitationModal
          onClose={() => setIsCreateOpen(false)}
          onCreated={(id) => {
            setCurrentHabitationId(id)
            setActiveRunId(null)
          }}
        />
      )}
    </header>
  )
}

export default function Layout() {
  const { setIsCopilotOpen } = useAppContext()

  useEffect(() => {
    function handler(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault()
        setIsCopilotOpen(true)
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [setIsCopilotOpen])

  return (
    <div className="flex h-screen flex-col bg-slate-50">
      <Header />
      <main className="flex-1 overflow-y-auto">
        <Outlet />
      </main>
      <ChatDrawer />
    </div>
  )
}
