import { baseApi } from '@/shared/api'

export type User = {
  id: number
  login: string
  /** `supervisor` — one per service, outside the teams. */
  role: 'admin' | 'user' | 'supervisor'
  is_protected: boolean
  /** A temporary password: only the password change is allowed until it is changed. */
  must_change_password?: boolean
  totp_enabled: boolean
  telegram_linked: boolean
  telegram_dm_enabled: boolean
  telegram_dm_days_before: number
  /** Without @; set by the admin or learned from Telegram. */
  telegram_username?: string | null
  telegram_user_id?: number | null
  created_at: string
  updated_at: string
}

/** The login is looked up inside the team. */
export type LoginRequest = { team: string; login: string; password: string }
export type PasswordChange = { current_password: string; new_password: string; totp_code?: string }
export type TotpSetup = { secret: string; otpauth_uri: string; expires_at: string }
type LoginResponse = {
  user: User
  session: { token: string; expires_at: string }
}

const sessionApi = baseApi.injectEndpoints({
  endpoints: (builder) => ({
    getMe: builder.query<User, void>({ query: () => 'auth/me', providesTags: ['Session'] }),
    login: builder.mutation<User, LoginRequest>({
      query: (body) => ({ url: 'auth/login', method: 'POST', body }),
      transformResponse: (response: LoginResponse) => response.user,
      invalidatesTags: ['Session'],
    }),
    logout: builder.mutation<void, void>({
      query: () => ({ url: 'auth/logout', method: 'POST' }),
    }),
    changePassword: builder.mutation<User, PasswordChange>({
      query: (body) => ({ url: 'auth/password', method: 'POST', body }),
      invalidatesTags: (_result, error) => error ? [] : ['Session'],
    }),
    beginTotp: builder.mutation<TotpSetup, string>({
      query: (current_password) => ({ url: 'auth/me/totp/begin', method: 'POST', body: { current_password } }),
    }),
    confirmTotp: builder.mutation<User, string>({
      query: (code) => ({ url: 'auth/me/totp/confirm', method: 'POST', body: { code } }),
      invalidatesTags: (_result, error) => error ? [] : ['Session'],
    }),
    updateDmNotifications: builder.mutation<User, boolean>({
      query: (telegram_dm_enabled) => ({ url: 'auth/me/notifications', method: 'PATCH', body: { telegram_dm_enabled } }),
      invalidatesTags: (_result, error) => error ? [] : ['Session'],
    }),
    updateDmReminderDays: builder.mutation<User, number>({
      query: (telegram_dm_days_before) => ({ url: 'auth/me/reminder-days', method: 'PATCH', body: { telegram_dm_days_before } }),
      invalidatesTags: (_result, error) => error ? [] : ['Session'],
    }),
  }),
})

export const { useGetMeQuery, useLoginMutation, useLogoutMutation, useChangePasswordMutation, useBeginTotpMutation, useConfirmTotpMutation, useUpdateDmNotificationsMutation, useUpdateDmReminderDaysMutation } = sessionApi
