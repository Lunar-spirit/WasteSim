import { createContext, useContext, useState, type ReactNode } from 'react'

// Defaults verified against a real, live-seeded SWMS dev database (not
// placeholders): DEFAULT_RUN_ID is a real COMPLETED BASE run, and it
// belongs to DEFAULT_HABITATION_ID — the READY "Shirva" habitation with a
// VALIDATED parameter set (id e1586d7d-...). A second habitation also
// exists seeded as "Shirva0" (id 5e1d9e42-0704-4f01-94c4-62861151f376) but
// it is still DRAFT (no committed parameters, cannot run a simulation) and
// does not own DEFAULT_RUN_ID — so it is deliberately not used as the
// default here, even though it was the literal id in this dashboard's own
// spec, since pairing it with DEFAULT_RUN_ID would 404 on first load.
export const DEFAULT_HABITATION_ID = 'e1586d7d-ae44-47b8-a291-56f30cfc3921'
export const DEFAULT_RUN_ID = '608df07c-0b28-4720-b33e-21ef0c83917c'

export type DashboardTab = 'simulation' | 'gis'

interface AppContextValue {
  currentHabitationId: string
  setCurrentHabitationId: (id: string) => void
  activeRunId: string | null
  setActiveRunId: (id: string | null) => void
  activeTab: DashboardTab
  setActiveTab: (tab: DashboardTab) => void
  isCopilotOpen: boolean
  setIsCopilotOpen: (open: boolean) => void
}

const AppContext = createContext<AppContextValue | null>(null)

export function AppProvider({ children }: { children: ReactNode }) {
  const [currentHabitationId, setCurrentHabitationId] = useState<string>(DEFAULT_HABITATION_ID)
  const [activeRunId, setActiveRunId] = useState<string | null>(DEFAULT_RUN_ID)
  const [activeTab, setActiveTab] = useState<DashboardTab>('simulation')
  const [isCopilotOpen, setIsCopilotOpen] = useState(false)

  return (
    <AppContext.Provider
      value={{
        currentHabitationId,
        setCurrentHabitationId,
        activeRunId,
        setActiveRunId,
        activeTab,
        setActiveTab,
        isCopilotOpen,
        setIsCopilotOpen,
      }}
    >
      {children}
    </AppContext.Provider>
  )
}

export function useAppContext(): AppContextValue {
  const ctx = useContext(AppContext)
  if (!ctx) throw new Error('useAppContext must be used within AppProvider')
  return ctx
}
