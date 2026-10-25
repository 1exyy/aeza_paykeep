import { baseApi } from '@/shared/api'
import type { Currency } from '@/shared/lib/money'
import type { OccurrenceState } from '../model/displayStatus'

type UserRef = { id: number; login: string }

export type PaymentOccurrence = {
  id: number
  recurring_payment_id: number
  title: string
  amount: string
  currency: Currency
  due_date: string
  status: 'paid' | 'unpaid'
  paid_date: string | null
  is_overdue: boolean
  is_paid_late: boolean
  state: OccurrenceState
  recurring_status: 'active' | 'stopped'
  /** From the recurring payment. */
  assign_all: boolean
  assignees: UserRef[]
  paid_by: UserRef | null
  paid_via: 'web' | 'telegram' | null
  reminder_sent_at: string | null
  attachments_count: number
  version: number
  created_at: string
  updated_at: string
}

export type PaymentOccurrencePage = { items: PaymentOccurrence[]; total: number; limit: number; offset: number }
export type OccurrenceListParams = {
  limit: number
  offset: number
  due_from?: string
  due_to?: string
  status?: 'paid' | 'unpaid'
  overdue?: boolean
  recurring_payment_id?: number
  /** Chosen explicitly or «all users». */
  assignee_id?: number
  sort?: 'due_date' | '-due_date'
}
export type PaymentOccurrencePatch = { status?: 'paid' | 'unpaid'; paid_date?: string; expected_version: number }

const occurrenceApi = baseApi.injectEndpoints({
  endpoints: (builder) => ({
    getOccurrences: builder.query<PaymentOccurrencePage, OccurrenceListParams>({
      query: (params) => ({ url: 'payment-occurrences', params }),
      providesTags: (result) => result
        ? [{ type: 'Occurrences', id: 'LIST' }, ...result.items.map(({ id }) => ({ type: 'Occurrences' as const, id }))]
        : [{ type: 'Occurrences', id: 'LIST' }],
    }),
    getOccurrence: builder.query<PaymentOccurrence, number>({
      query: (id) => `payment-occurrences/${id}`,
      providesTags: (_result, _error, id) => [{ type: 'Occurrences', id }],
    }),
    updateOccurrence: builder.mutation<PaymentOccurrence, { id: number; patch: PaymentOccurrencePatch }>({
      query: ({ id, patch }) => ({ url: `payment-occurrences/${id}`, method: 'PATCH', body: patch }),
      invalidatesTags: (_result, error) => error ? [] : ['Occurrences', 'Summary', 'Calendar', 'Budget', 'Audit', 'Deliveries'],
    }),
  }),
})

export const { useGetOccurrencesQuery, useGetOccurrenceQuery, useUpdateOccurrenceMutation } = occurrenceApi
