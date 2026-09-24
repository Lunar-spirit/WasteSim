import { useQuery } from '@tanstack/react-query'
import { LayoutDashboard, Loader2, LogOut, Map as MapIcon, Sparkles } from 'lucide-react'
import { useEffect, useState } from 'react'
import { AUTH_EXPIRED_EVENT, isAuthenticated, login, logout } from './api/client'
import { fetchHabitations } from './api/endpoints'
import ChatDrawer from './components/ChatDrawer'
import GisMap from './components/GisMap'
import SimulationDashboard from './components/SimulationDashboard'
import { AppProvider, useAppContext } from './context/AppContext'

function LoginScreen({ onLoggedIn }: { onLoggedIn: () => void }) {
  const [email, setEmail] = useState('admin@example.com')
  const [password, setPassword] = useState('Password123!')
  const [error, setError] = useState<string | null>(null)
  const [isSubmitting, setIsSubmitting] = useState(false)

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError(null)
    setIsSubmitting(true)
    try {
      await login(email, password)
      onLoggedIn()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Login failed')
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <div className="flex h-screen items-center justify-center bg-slate-50">
      <form onSubmit={handleSubmit} className="w-full max-w-sm rounded-2xl border border-slate-200 bg-white p-8 shadow-sm">
        <div className="mb-6 flex items-center gap-2">
          <Sparkles className="h-5 w-5 text-emerald-600" />
          <h1 className="text-lg font-bold text-slate-900">SWMS Lite</h1>
        </div>
        <div className="flex flex-col gap-3">
          <label className="flex flex-col gap-1 text-sm">
            <span className="font-medium text-slate-700">Email</span>
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500"
              required
            />
          </label>
          <label className="flex flex-col gap-1 text-sm">
            <span className="font-medium text-slate-700">Password</span>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500"
              required
            />
          </label>
        </div>
        {error && <p className="mt-3 text-xs text-red-600">{error}</p>}
        <button
          type="submit"
          disabled={isSubmitting}
          className="mt-5 flex w-full items-center justify-center gap-2 rounded-lg bg-emerald-600 px-4 py-2.5 text-sm font-semibold text-white transition hover:bg-emerald-700 disabled:opacity-60"
        >
          {isSubmitting && <Loader2 className="h-4 w-4 animate-spin" />}
          Sign in
        </button>
        <p className="mt-4 text-center text-xs text-slate-400">
          Backend: {import.meta.env.VITE_API_BASE_URL ?? 'http://127.0.0.1:8000'}
        </p>
      </form>
    </div>
  )
}

function Header() {
  const { currentHabitationId, setCurrentHabitationId, setActiveRunId, activeTab, setActiveTab, setIsCopilotOpen } =
    useAppContext()

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
    <header className="flex items-center justify-between border-b border-slate-200 bg-white px-6 py-3">
      <div className="flex items-center gap-6">
        <div className="flex items-center gap-2">
          <Sparkles className="h-5 w-5 text-emerald-600" />
          <span className="text-base font-bold text-slate-900">SWMS Lite</span>
        </div>

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

        <nav className="flex items-center gap-1 rounded-lg bg-slate-100 p-1">
          <button
            type="button"
            onClick={() => setActiveTab('simulation')}
            className={`flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-medium transition ${
              activeTab === 'simulation' ? 'bg-white text-slate-900 shadow-sm' : 'text-slate-500 hover:text-slate-700'
            }`}
          >
            <LayoutDashboard className="h-3.5 w-3.5" />
            Simulation & Budget
          </button>
          <button
            type="button"
            onClick={() => setActiveTab('gis')}
            className={`flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-medium transition ${
              activeTab === 'gis' ? 'bg-white text-slate-900 shadow-sm' : 'text-slate-500 hover:text-slate-700'
            }`}
          >
            <MapIcon className="h-3.5 w-3.5" />
            GIS Map View
          </button>
        </nav>
      </div>

      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={() => setIsCopilotOpen(true)}
          className="flex items-center gap-2 rounded-lg bg-emerald-600 px-3.5 py-2 text-sm font-medium text-white transition hover:bg-emerald-700"
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
    </header>
  )
}

function DashboardShell() {
  const { activeTab } = useAppContext()
  return (
    <div className="flex h-screen flex-col bg-slate-50">
      <Header />
      <main className="flex-1 overflow-y-auto">
        {activeTab === 'simulation' ? <SimulationDashboard /> : <GisMap />}
      </main>
      <ChatDrawer />
    </div>
  )
}

export default function App() {
  const [authed, setAuthed] = useState(isAuthenticated())

  useEffect(() => {
    const handler = () => setAuthed(false)
    window.addEventListener(AUTH_EXPIRED_EVENT, handler)
    return () => window.removeEventListener(AUTH_EXPIRED_EVENT, handler)
  }, [])

  if (!authed) {
    return <LoginScreen onLoggedIn={() => setAuthed(true)} />
  }

  return (
    <AppProvider>
      <DashboardShell />
    </AppProvider>
  )
}
