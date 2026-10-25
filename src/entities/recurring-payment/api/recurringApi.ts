import { baseApi } from '@/shared/api'
import type { Currency } from '@/shared/lib/money'

export type UserRef = { id: number; login: string }

/** `every_n_days` uses `interval_days` (1–365); `once` has a single period. */
export type Periodicity = 'once' | 'daily' | 'weekly' | 'monthly' | 'every_n_days'

export type RecurringPayment = {
  id: number
  title: string
  amount: string
  currency: Currency
  periodicity: Periodicity
  interval_days?: number | null
  anchor_day: number
  first_due_date: string
  next_due_date: string | null
  status: 'active' | 'stopped'
  /** A one-time payment that was paid and completed automatically (status is then `stopped`). */
  completed?: boolean
  created_at: string
  stopped_at: string | null
  created_by: UserRef
  /** Everyone (including users added later) is responsible; `assignees` is then empty. */
  assign_all: boolean
  assignees: UserRef[]
  version: number
}

export type RecurringPaymentCreate = Pick<RecurringPayment, 'title' | 'amount' | 'currency' | 'periodicity'> & {
  next_due_date: string
  interval_days?: number
  assignee_ids?: number[]
  assign_all?: boolean
}
/** Only the fields to change. */
export type RecurringPaymentPatch = {
  id: number
  title?: string
  amount?: string
  currency?: Currency
  next_due_date?: string
  periodicity?: Periodicity
  interval_days?: number | null
  assignee_ids?: number[]
  assign_all?: boolean
  expected_version: number
}
export type RecurringPaymentPage = { items: RecurringPayment[]; total: number; limit: number; offset: number }

const changedTags = ['RecurringPayments', 'Occurrences', 'Summary', 'Calendar', 'Budget', 'Audit', 'Deliveries'] as const

const recurringApi = baseApi.injectEndpoints({
  endpoints: (builder) => ({
    getRecurringPayments: builder.query<RecurringPaymentPage, { limit: number; offset: number }>({
      query: (params) => ({ url: 'recurring-payments', params }),
      providesTags: ['RecurringPayments'],
    }),
    getRecurringPayment: builder.query<RecurringPayment, number>({
      query: (id) => ({ url: `recurring-payments/${id}` }),
      providesTags: ['RecurringPayments'],
    }),
    createRecurringPayment: builder.mutation<RecurringPayment, RecurringPaymentCreate>({
      query: (body) => ({ url: 'recurring-payments', method: 'POST', body }),
      invalidatesTags: (_result, error) => error ? [] : [...changedTags],
    }),
    updateRecurringPayment: builder.mutation<RecurringPayment, RecurringPaymentPatch>({
      query: ({ id, ...body }) => ({ url: `recurring-payments/${id}`, method: 'PATCH', body }),
      invalidatesTags: (_result, error) => error ? [] : [...changedTags],
    }),
    stopRecurringPayment: builder.mutation<RecurringPayment, number>({
      query: (id) => ({ url: `recurring-payments/${id}`, method: 'DELETE' }),
      invalidatesTags: (_result, error) => error ? [] : [...changedTags],
    }),
  }),
})

export const {
  useGetRecurringPaymentsQuery,
  useGetRecurringPaymentQuery,
  useCreateRecurringPaymentMutation,
  useUpdateRecurringPaymentMutation,
  useStopRecurringPaymentMutation,
} = recurringApi
