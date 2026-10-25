import { describe, expect, it } from 'vitest'
import { assigneesLabel } from './assignees'

describe('подпись ответственных за платёж', () => {
  it('показывает «всех», конкретных и отсутствие ответственных', () => {
    expect(assigneesLabel({ assign_all: true, assignees: [] })).toBe('Все пользователи')
    expect(assigneesLabel({ assign_all: false, assignees: [{ id: 2, login: 'anna' }, { id: 3, login: 'boris' }] })).toBe('anna, boris')
    expect(assigneesLabel({ assign_all: false, assignees: [] })).toBe('Не назначены')
  })
})
