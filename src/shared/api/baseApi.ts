import { createApi, fetchBaseQuery } from '@reduxjs/toolkit/query/react'
import type { BaseQueryFn, FetchArgs, FetchBaseQueryError } from '@reduxjs/toolkit/query'

const rawBaseQuery = fetchBaseQuery({ baseUrl: '/api/v1/', credentials: 'same-origin' })
const baseQuery: BaseQueryFn<string | FetchArgs, unknown, FetchBaseQueryError> = async (args, api, extraOptions) => {
  const result = await rawBaseQuery(args, api, extraOptions)
  if (result.error?.status === 401 && api.endpoint !== 'getMe' && api.endpoint !== 'login') {
    queueMicrotask(() => api.dispatch(baseApi.util.resetApiState()))
  }
  return result
}

export const baseApi = createApi({
  reducerPath: 'api',
  baseQuery,
  refetchOnFocus: true,
  refetchOnReconnect: true,
  tagTypes: ['Session', 'Config', 'Occurrences', 'RecurringPayments', 'Summary', 'Users', 'Calendar', 'Budget', 'Attachments', 'Audit', 'Deliveries', 'NotificationSettings', 'Applications'],
  endpoints: () => ({}),
})
