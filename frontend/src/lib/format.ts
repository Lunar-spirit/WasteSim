export function formatCrores(value: number): string {
  return `₹${(value / 1e7).toFixed(2)} Cr`
}

export function formatInr(value: number): string {
  return `₹${value.toLocaleString('en-IN', { maximumFractionDigits: 0 })}`
}

export function formatTonnes(value: number): string {
  return `${value.toLocaleString('en-IN', { maximumFractionDigits: 0 })} t`
}
