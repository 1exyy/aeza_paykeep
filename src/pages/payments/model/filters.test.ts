import { describe, expect, it } from 'vitest'
import { resolveAssignee, statusQuery } from './filters'

describe('payments filters', () => {
  it('maps the status filter to the API query', () => {
    expect(statusQuery('upcoming')).toEqual({ status: 'unpaid', overdue: false })
    expect(statusQuery('overdue')).toEqual({ overdue: true })
    expect(statusQuery('paid')).toEqual({ status: 'paid' })
    expect(statusQuery('all')).toEqual({})
  })

  it('presets the assignee filter to the user', () => {
    expect(resolveAssignee(null, 'user')).toBe('me')
    expect(resolveAssignee(null, 'admin')).toBe('all')
    expect(resolveAssignee('all', 'user')).toBe('all')
    expect(resolveAssignee('5', 'admin')).toBe(5)
    expect(resolveAssignee('5', 'user')).toBe('me')
  })
})
