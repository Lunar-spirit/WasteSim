import { Loader2, Sparkles } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Navigate, Route, HashRouter, Routes } from 'react-router-dom'
import { AUTH_EXPIRED_EVENT, isAuthenticated, login, register } from './api/client'
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
  // Registration is the first thing offered, per the product's own
  // preference — a brand-new visitor with no account yet lands here, not
  // on a sign-in form assuming they already have one.
  const [mode, setMode] = useState<'register' | 'login'>('register')
  const [fullName, setFullName] = useState('')
  const [email, setEmail] = useState(mode === 'login' ? 'admin@example.com' : '')
  const [password, setPassword] = useState(mode === 'login' ? 'Password123!' : '')
  const [error, setError] = useState<string | null>(null)
  const [isSubmitting, setIsSubmitting] = useState(false)

  function switchMode(next: 'register' | 'login') {
    setMode(next)
    setError(null)
    // The admin demo credentials are only a convenience for the sign-in
    // form; a fresh registration should never start pre-filled with them.
    setEmail(next === 'login' ? 'admin@example.com' : '')
    setPassword(next === 'login' ? 'Password123!' : '')
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError(null)
    setIsSubmitting(true)
    try {
      if (mode === 'register') {
        await register(email, password, fullName)
      } else {
        await login(email, password)
      }
      onLoggedIn()
    } catch (err) {
      setError(err instanceof Error ? err.message : `${mode === 'register' ? 'Registration' : 'Login'} failed`)
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

        <div className="mb-5 flex rounded-lg bg-slate-100 p-1 text-sm font-medium">
          <button
            type="button"
            onClick={() => switchMode('register')}
            className={`flex-1 rounded-md py-1.5 transition ${mode === 'register' ? 'bg-white text-slate-900 shadow-sm' : 'text-slate-500'}`}
          >
            Create account
          </button>
          <button
            type="button"
            onClick={() => switchMode('login')}
            className={`flex-1 rounded-md py-1.5 transition ${mode === 'login' ? 'bg-white text-slate-900 shadow-sm' : 'text-slate-500'}`}
          >
            Sign in
          </button>
        </div>

        <div className="flex flex-col gap-3">
          {mode === 'register' && (
            <label className="flex flex-col gap-1 text-sm">
              <span className="font-medium text-slate-700">Full name</span>
              <input
                type="text"
                value={fullName}
                onChange={(e) => setFullName(e.target.value)}
                placeholder="e.g. Asha Rao"
                className="rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500"
                required
              />
            </label>
          )}
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
              minLength={mode === 'register' ? 8 : undefined}
              className="rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500"
              required
            />
            {mode === 'register' && <span className="text-xs text-slate-400">At least 8 characters.</span>}
          </label>
        </div>
        {error && <p className="mt-3 text-xs text-red-600">{error}</p>}
        <button
          type="submit"
          disabled={isSubmitting}
          className="mt-5 flex w-full items-center justify-center gap-2 rounded-lg bg-emerald-600 px-4 py-2.5 text-sm font-semibold text-white transition hover:bg-emerald-700 disabled:opacity-60"
        >
          {isSubmitting && <Loader2 className="h-4 w-4 animate-spin" />}
          {mode === 'register' ? 'Create account' : 'Sign in'}
        </button>
        {mode === 'register' && (
          <p className="mt-3 text-center text-xs text-slate-400">
            New accounts start as a Researcher: read access to every ready habitation, plus running simulations,
            sensitivity sweeps, comparisons and reports. An admin can grant edit access on a specific habitation
            afterwards for parameter and optimization work.
          </p>
        )}
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
