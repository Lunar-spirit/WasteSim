// Indian currency formatting — shared by every page that surfaces a cost
// figure. Crores (1e7) is the unit Indian financial reporting actually
// uses, not lakhs or plain millions, so a figure like 121946521.4 reads as
// "₹12.19 Cr", not "₹12,19,46,521" (the raw rupee amount is still available,
// just demoted to a hover tooltip — see formatInrFull).

export function formatInrCrores(value: number): string {
  const crores = value / 1e7
  return `₹${crores.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} Cr`
}

export function formatInrFull(value: number): string {
  return `₹${Math.round(value).toLocaleString('en-IN')}`
}

export const RESTRICTED_CURRENCY_LABEL = '🔒 Restricted (Researcher/Planner Only)'
