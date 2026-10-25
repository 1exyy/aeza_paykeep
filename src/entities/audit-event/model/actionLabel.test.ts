import { describe, expect, it } from 'vitest'
import { auditActionLabel } from './actionLabel'

describe('auditActionLabel', () => {
  it('labels payment actions and keeps unknown ones', () => {
    expect(auditActionLabel('occurrence.mark_paid')).toBe('Отмечено «оплачено»')
    expect(auditActionLabel('something.else')).toBe('something.else')
  })
})
