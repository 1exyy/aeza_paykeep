import type { PaymentDisplayStatus } from '../ui/PaymentStatusBadge'

// PaymentOccurrence.state из OpenAPI v0.1.1, без расчёта по часам устройства.
export type OccurrenceState = 'upcoming' | 'overdue' | 'paid' | 'paid_late'

const displayStatuses: Record<OccurrenceState, PaymentDisplayStatus> = {
  upcoming: 'unpaid',
  overdue: 'overdue',
  paid: 'paid',
  paid_late: 'paid-late',
}

export function toPaymentDisplayStatus(state: OccurrenceState): PaymentDisplayStatus {
  return displayStatuses[state]
}
