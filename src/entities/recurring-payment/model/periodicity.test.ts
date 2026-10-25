import { describe, expect, it } from 'vitest'
import { parseInterval, periodicityLabel, statusLabel } from './periodicity'

describe('periodicity', () => {
  it('labels every periodicity', () => {
    expect(periodicityLabel({ periodicity: 'monthly' })).toBe('Ежемесячно')
    expect(periodicityLabel({ periodicity: 'every_n_days', interval_days: 10 })).toBe('Каждые 10 дн.')
    expect(periodicityLabel({ periodicity: 'once' })).toBe('Разовый')
  })

  it('validates the interval', () => {
    expect(parseInterval('10')).toBe(10)
    expect(typeof parseInterval('0')).toBe('string')
    expect(typeof parseInterval('366')).toBe('string')
    expect(typeof parseInterval('1.5')).toBe('string')
  })

  it('shows a completed one-time payment', () => {
    expect(statusLabel({ status: 'stopped', completed: true })).toBe('Завершён (оплачен)')
    expect(statusLabel({ status: 'stopped' })).toBe('Прекращён')
  })
})
