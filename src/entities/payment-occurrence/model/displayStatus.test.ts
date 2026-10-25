import { describe, expect, it } from 'vitest'
import { toPaymentDisplayStatus } from './displayStatus'

describe('состояние периода из API', () => {
  it('различает неоплаченный долг и оплату с опозданием', () => {
    expect(toPaymentDisplayStatus('upcoming')).toBe('unpaid')
    expect(toPaymentDisplayStatus('overdue')).toBe('overdue')
    expect(toPaymentDisplayStatus('paid')).toBe('paid')
    expect(toPaymentDisplayStatus('paid_late')).toBe('paid-late')
  })
})
