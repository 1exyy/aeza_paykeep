import { baseApi } from '@/shared/api'
import type { Currency } from '@/shared/lib/money'

export type CurrencyTotals = { currency: Currency; total: string; paid: string; unpaid: string; overdue: string; count: number }
export type Summary = { from: string; to: string; today: string; currencies: CurrencyTotals[] }

const summaryApi = baseApi.injectEndpoints({
  endpoints: (builder) => ({
    getSummary: builder.query<Summary, { from: string; to: string }>({
      query: (params) => ({ url: 'payments/summary', params }),
      providesTags: ['Summary'],
    }),
  }),
})

export const { useGetSummaryQuery } = summaryApi
