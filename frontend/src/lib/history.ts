import { useEffect, useState } from 'react'

// The backend intentionally exposes no "list optimizations/comparisons/
// sensitivity-analyses for a habitation" endpoint (only get-by-id) — each
// created run is a real, addressable resource, but nothing indexes them
// per habitation. This is a thin, real (not mocked) client-side index of
// IDs this browser has created, so those pages have something to list
// without inventing a backend endpoint that doesn't exist. Survives
// reloads via localStorage; scoped per habitation + resource kind.

function storageKey(kind: string, habitationId: string): string {
  return `swms:history:${kind}:${habitationId}`
}

export function readHistory(kind: string, habitationId: string): string[] {
  try {
    const raw = localStorage.getItem(storageKey(kind, habitationId))
    if (!raw) return []
    const parsed: unknown = JSON.parse(raw)
    // Defensive: a bad write elsewhere (e.g. pushing an undefined id) can
    // leave a null/non-string entry in storage; filter rather than let a
    // caller's `.slice()`/`.startsWith()` crash on it.
    return Array.isArray(parsed) ? parsed.filter((x): x is string => typeof x === 'string') : []
  } catch {
    return []
  }
}

export function pushHistory(kind: string, habitationId: string, id: string): void {
  try {
    const existing = readHistory(kind, habitationId)
    const next = [id, ...existing.filter((x) => x !== id)].slice(0, 20)
    localStorage.setItem(storageKey(kind, habitationId), JSON.stringify(next))
    window.dispatchEvent(new CustomEvent(`swms:history:${kind}`, { detail: { habitationId } }))
  } catch {
    // localStorage unavailable (private mode, quota) — history just won't persist.
  }
}

/** Reactive read of a habitation's history list for one resource kind. */
export function useHistory(kind: string, habitationId: string): string[] {
  const [items, setItems] = useState<string[]>(() => readHistory(kind, habitationId))

  useEffect(() => {
    setItems(readHistory(kind, habitationId))
    const handler = () => setItems(readHistory(kind, habitationId))
    window.addEventListener(`swms:history:${kind}`, handler)
    return () => window.removeEventListener(`swms:history:${kind}`, handler)
  }, [kind, habitationId])

  return items
}

// The one "current editable draft" parameter set per habitation, shared
// across GIS Studio's Auto-Populate (which creates/writes into a draft
// behind the scenes via the backend's own _resolve_target_parameter_set)
// and the Parameters page (which otherwise has no way to discover that a
// draft already exists, and would create a second, blank one instead of
// reusing the auto-populated data).
export function draftPsidKey(habitationId: string): string {
  return `swms:draft-psid:${habitationId}`
}

export function getDraftPsid(habitationId: string): string | null {
  try {
    return localStorage.getItem(draftPsidKey(habitationId))
  } catch {
    return null
  }
}

export function setDraftPsid(habitationId: string, psid: string): void {
  try {
    localStorage.setItem(draftPsidKey(habitationId), psid)
    window.dispatchEvent(new CustomEvent('swms:draft-psid', { detail: { habitationId } }))
  } catch {
    // localStorage unavailable — the draft still exists server-side, the
    // user just won't be auto-navigated to it from another page.
  }
}

export function clearDraftPsid(habitationId: string): void {
  try {
    localStorage.removeItem(draftPsidKey(habitationId))
    window.dispatchEvent(new CustomEvent('swms:draft-psid', { detail: { habitationId } }))
  } catch {
    // no-op
  }
}
