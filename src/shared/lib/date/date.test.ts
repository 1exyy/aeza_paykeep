import { describe, expect, it } from 'vitest'
import { formatDateOnly, isDateOnly, shiftDateOnly } from './date'

describe('календарные даты без зоны устройства', () => {
  it('сохраняет дату независимо от зоны устройства', () => {
    expect(formatDateOnly('2026-03-01')).toBe('01.03.2026')
    expect(isDateOnly('2026-02-29')).toBe(false)
  })
  it('считает границу фактической даты по date-only без зоны устройства', () => {
    expect(shiftDateOnly('2028-03-01', -1)).toBe('2028-02-29')
    expect(shiftDateOnly('2027-03-01', -1)).toBe('2027-02-28')
  })
})
