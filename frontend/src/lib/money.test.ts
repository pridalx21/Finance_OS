import { describe, expect, it } from 'vitest'
import { formatCHF, formatDate, parseAmountToCents } from './money'

describe('parseAmountToCents', () => {
  it('parses a plain amount', () => {
    expect(parseAmountToCents('12.34')).toBe(1234)
  })

  it('parses an amount without decimals', () => {
    expect(parseAmountToCents('12')).toBe(1200)
  })

  it('parses a single decimal', () => {
    expect(parseAmountToCents('12.3')).toBe(1230)
  })

  it('accepts a leading or trailing space', () => {
    expect(parseAmountToCents(' 12.34 ')).toBe(1234)
  })

  it('accepts a thousands separator', () => {
    expect(parseAmountToCents("1'234.56")).toBe(123456)
  })

  it('rounds the third decimal half up', () => {
    expect(parseAmountToCents('8.115')).toBe(812)
    expect(parseAmountToCents('8.114')).toBe(811)
    expect(parseAmountToCents('8.005')).toBe(801)
  })

  it('parses a negative amount', () => {
    expect(parseAmountToCents('-12.34')).toBe(-1234)
  })

  it('rejects invalid input', () => {
    expect(parseAmountToCents('')).toBeNull()
    expect(parseAmountToCents('abc')).toBeNull()
    expect(parseAmountToCents('12.34.56')).toBeNull()
    expect(parseAmountToCents('12,34')).toBeNull()
    expect(parseAmountToCents('.5')).toBeNull()
  })

  it('does not silently truncate more than three decimals', () => {
    expect(parseAmountToCents('12.3456')).toBeNull()
  })

  it('is exact for values that a float calculation would round wrongly', () => {
    // 8.115 * 100 === 811.4999999999999 in floating point
    expect(parseAmountToCents('8.115')).toBe(812)
    // 1.005 * 100 === 100.49999999999999 in floating point
    expect(parseAmountToCents('1.005')).toBe(101)
  })
})

describe('formatCHF', () => {
  it('formats Rappen as CHF', () => {
    expect(formatCHF(1234)).toBe('12.34 CHF')
  })

  it('formats zero', () => {
    expect(formatCHF(0)).toBe('0.00 CHF')
  })

  it('formats a negative amount', () => {
    expect(formatCHF(-500)).toBe('-5.00 CHF')
  })

  it('keeps two decimals', () => {
    expect(formatCHF(5)).toBe('0.05 CHF')
    expect(formatCHF(50)).toBe('0.50 CHF')
  })

  it('groups thousands', () => {
    expect(formatCHF(123456)).toMatch(/^1.234\.56 CHF$/)
  })
})

describe('formatDate', () => {
  it('formats an ISO date', () => {
    expect(formatDate('2026-05-01T00:00:00')).toMatch(/2026/)
  })

  it('returns the input for an invalid date', () => {
    expect(formatDate('not-a-date')).toBe('not-a-date')
  })
})
