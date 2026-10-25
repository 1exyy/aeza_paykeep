import type { OccurrenceListParams } from '@/entities/payment-occurrence'

export type StatusFilter = 'all' | 'upcoming' | 'overdue' | 'paid'
export const statusOptions: { value: StatusFilter; label: string }[] = [
  { value: 'all', label: 'Все статусы' },
  { value: 'upcoming', label: 'Ожидают оплаты' },
  { value: 'overdue', label: 'Просрочены' },
  { value: 'paid', label: 'Оплачены' },
]

export function isStatusFilter(value: string | null): value is StatusFilter {
  return statusOptions.some((option) => option.value === value)
}

/** Status filter → API query (status + overdue). */
export function statusQuery(status: StatusFilter): Pick<OccurrenceListParams, 'status' | 'overdue'> {
  if (status === 'upcoming') return { status: 'unpaid', overdue: false }
  if (status === 'overdue') return { overdue: true }
  if (status === 'paid') return { status: 'paid' }
  return {}
}

/**
 * Assignee filter from the URL: 'all', 'me' or a user id. A user sees their own payments by
 * default; an admin sees everything.
 */
export function resolveAssignee(raw: string | null, role: 'admin' | 'user' | 'supervisor'): 'all' | 'me' | number {
  if (raw === 'all' || raw === 'me') return raw
  const id = Number(raw)
  if (raw && Number.isSafeInteger(id) && id > 0) return role === 'admin' ? id : 'me'
  return role === 'admin' ? 'all' : 'me'
}
