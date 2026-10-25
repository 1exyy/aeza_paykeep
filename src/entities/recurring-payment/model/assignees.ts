import type { UserRef } from '../api/recurringApi'

/** Form value of the responsible users. */
export type AssigneesValue = { assign_all: boolean; assignee_ids: number[] }

export function assigneesLabel(item: { assign_all: boolean; assignees: readonly UserRef[] }): string {
  if (item.assign_all) return 'Все пользователи'
  if (item.assignees.length === 0) return 'Не назначены'
  return item.assignees.map(({ login }) => login).join(', ')
}
