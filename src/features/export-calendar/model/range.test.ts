import { describe, expect, it } from 'vitest'
import { exportRange } from './range'

describe('exportRange', () => {
  it('covers the shown month or its year', () => {
    expect(exportRange('2026-02', 'month')).toEqual({ from: '2026-02-01', to: '2026-02-28' })
    expect(exportRange('2028-02', 'month')).toEqual({ from: '2028-02-01', to: '2028-02-29' })
    expect(exportRange('2026-11', 'year')).toEqual({ from: '2026-01-01', to: '2026-12-31' })
  })
})
