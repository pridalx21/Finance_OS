/**
 * Money helpers.
 *
 * Amounts are integers in the smallest currency unit (Rappen for CHF).
 * The conversion between a user input ("12.34") and the integer value
 * (1234) is done with string operations - no floating point arithmetic for
 * money.
 */

/**
 * Parse a user input into Rappen (integer cents).
 *
 * Returns `null` if the input is not a valid amount. Values with more than
 * two decimals are rounded half up (ADR-005); values with more than three
 * decimals are rejected instead of being silently truncated.
 */
export function parseAmountToCents(value: string): number | null {
  const cleaned = value.trim().replace(/[\s'’]/g, '')
  if (!cleaned) return null

  const match = /^(-)?(\d+)(?:\.(\d{1,3}))?$/.exec(cleaned)
  if (!match) return null

  const negative = match[1] === '-'
  const units = Number(match[2])
  const decimals = match[3] ?? ''
  if (!Number.isSafeInteger(units)) return null

  // Third decimal is rounded half up, the rest is cut off.
  const millis = Number((decimals + '000').slice(0, 3))
  const cents = units * 100 + Math.floor((millis + 5) / 10)

  return negative ? -cents : cents
}

/**
 * Format Rappen as a CHF amount ("1'234.56 CHF").
 *
 * The integer part is formatted by Intl, the fraction is added as text -
 * no floating point conversion takes place.
 */
export function formatCHF(cents: number): string {
  const negative = cents < 0
  const absolute = Math.abs(Math.trunc(cents))
  const units = Math.floor(absolute / 100)
  const fraction = absolute % 100

  const grouped = new Intl.NumberFormat('de-CH', { maximumFractionDigits: 0 }).format(units)
  return `${negative ? '-' : ''}${grouped}.${String(fraction).padStart(2, '0')} CHF`
}

/** Format a date (ISO string) as a Swiss date. */
export function formatDate(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleDateString('de-CH', { day: '2-digit', month: '2-digit', year: 'numeric' })
}
