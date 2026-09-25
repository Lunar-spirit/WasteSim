import { Loader2, Sparkles } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Navigate, Route, HashRouter, Routes } from 'react-router-dom'
import { AUTH_EXPIRED_EVENT, isAuthenticated, login } from './api/client'
import Layout from './components/Layout'
import { AppProvider } from './context/AppContext'
import ComparisonPage from './pages/ComparisonPage'
import GisStudioPage from './pages/GisStudioPage'
import OptimizationPage from './pages/OptimizationPage'
import ParametersPage from './pages/ParametersPage'
import ReportsPage from './pages/ReportsPage'
import ScenariosPage from './pages/ScenariosPage'
import SensitivityPage from './pages/SensitivityPage'
import SimulationPage from './pages/SimulationPage'

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
      <HashRouter>
        <Routes>
          <Route element={<Layout />}>
            <Route index element={<Navigate to="/simulation" replace />} />
            <Route path="/gis" element={<GisStudioPage />} />
            <Route path="/parameters" element={<ParametersPage />} />
            <Route path="/simulation" element={<SimulationPage />} />
            <Route path="/scenarios" element={<ScenariosPage />} />
            <Route path="/sensitivity" element={<SensitivityPage />} />
            <Route path="/optimization" element={<OptimizationPage />} />
            <Route path="/comparison" element={<ComparisonPage />} />
            <Route path="/reports" element={<ReportsPage />} />
            <Route path="*" element={<Navigate to="/simulation" replace />} />
          </Route>
        </Routes>
      </HashRouter>
    </AppProvider>
  )
}
