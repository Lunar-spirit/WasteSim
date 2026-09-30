import { useState } from 'react'
import type { SimulationRun } from '../types/api'

/**
 * The "which completed BASE run is this workspace acting on" selector used
 * identically on the Scenarios, Sensitivity, and Optimization pages.
 *
 * Without a default, a habitation whose activeRunId isn't itself a
 * completed BASE run (e.g. right after switching habitations, or after the
 * active run turned out to be a SCENARIO/OPTIMIZED run instead) left the
 * dropdown sitting on an empty "Select a completed BASE run…" placeholder
 * even though real options existed right there in the list — found live,
 * and easy to mistake for the page being broken rather than just needing
 * one extra click. Falling back to the most recently created completed
 * BASE run means there's always something sensible pre-selected whenever
 * one exists.
 */
export function useSelectedBaseRun(baseRuns: SimulationRun[], activeRunId: string | null): [string | null, (id: string) => void] {
  const [manualId, setManualId] = useState<string | null>(null)
  const activeIsValidBase = activeRunId != null && baseRuns.some((r) => r.id === activeRunId)
  const selected = manualId ?? (activeIsValidBase ? activeRunId : null) ?? baseRuns[0]?.id ?? null
  return [selected, setManualId]
}
