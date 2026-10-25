import { baseApi } from '@/shared/api'
import type { User } from '@/entities/session'

export type UserPage = { items: User[]; total: number; limit: number; offset: number }
/** `telegram` is «@username» or a numeric ID; '' or null unlinks. */
export type UserCreate = { login: string; password: string; telegram?: string }
export type UserPatch = { id: number; login?: string; password?: string; telegram?: string | null }

const userApi = baseApi.injectEndpoints({
  endpoints: (builder) => ({
    getUsers: builder.query<UserPage, { limit: number; offset: number }>({
      query: (params) => ({ url: 'users', params }),
      providesTags: ['Users'],
    }),
    createUser: builder.mutation<User, UserCreate>({
      query: (body) => ({ url: 'users', method: 'POST', body }),
      invalidatesTags: (_result, error) => error ? [] : ['Users', 'Audit'],
    }),
    updateUser: builder.mutation<User, UserPatch>({
      query: ({ id, ...body }) => ({ url: `users/${id}`, method: 'PATCH', body }),
      invalidatesTags: (_result, error) => error ? [] : ['Users', 'Audit', 'RecurringPayments', 'Occurrences'],
    }),
    deleteUser: builder.mutation<void, number>({
      query: (id) => ({ url: `users/${id}`, method: 'DELETE' }),
      invalidatesTags: (_result, error) => error ? [] : ['Users', 'Audit'],
    }),
  }),
})

export const { useGetUsersQuery, useCreateUserMutation, useUpdateUserMutation, useDeleteUserMutation } = userApi
