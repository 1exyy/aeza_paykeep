import { baseApi } from '@/shared/api'
import type { Currency } from '@/shared/lib/money'

export type BudgetTotals = { currency: Currency; planned: string; existing_paid: string; existing_unpaid: string; projected: string }
export type Budget = { period: 'month' | 'year'; from: string; to: string; currencies: BudgetTotals[] }
export type BudgetParams = { period: 'month' | 'year'; year: number; month?: number }

const budgetApi = baseApi.injectEndpoints({
  endpoints: (builder) => ({
    getBudget: builder.query<Budget, BudgetParams>({
      query: (params) => ({ url: 'budget', params }),
      providesTags: ['Budget'],
    }),
  }),
})

export const { useGetBudgetQuery } = budgetApi
