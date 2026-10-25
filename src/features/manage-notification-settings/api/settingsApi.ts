import { baseApi } from '@/shared/api'

export type SmtpSecurity = 'starttls' | 'ssl' | 'none'
export type SettingsChannel = 'telegram' | 'email' | 'webhook'

/** Values saved by the admin, otherwise from .env. Secrets are never returned. */
export type NotificationSettings = {
  telegram_chat_id: string
  telegram_bot_configured: boolean
  telegram_bot_username: string
  smtp_host: string
  smtp_port: number
  smtp_user: string
  smtp_password_set: boolean
  smtp_from: string
  smtp_security: SmtpSecurity
  email_recipients: string[]
  webhook_url: string
  webhook_secret_set: boolean
  channels: Record<SettingsChannel, boolean>
  updated_at: string | null
  updated_by: string | null
  version: number
}

export type NotificationSettingsPatch = Partial<{
  telegram_chat_id: string
  smtp_host: string
  smtp_port: number
  smtp_user: string
  smtp_password: string
  smtp_from: string
  smtp_security: SmtpSecurity
  email_recipients: string[]
  webhook_url: string
  webhook_secret: string
}> & { expected_version: number }

export type SettingsTestResult = { channel: SettingsChannel; ok: boolean; error: string | null }

const settingsApi = baseApi.injectEndpoints({
  endpoints: (builder) => ({
    getNotificationSettings: builder.query<NotificationSettings, void>({
      query: () => 'settings/notifications',
      providesTags: ['NotificationSettings'],
    }),
    updateNotificationSettings: builder.mutation<NotificationSettings, NotificationSettingsPatch>({
      query: (body) => ({ url: 'settings/notifications', method: 'PATCH', body }),
      invalidatesTags: (_result, error) => error ? [] : ['NotificationSettings', 'Config', 'Audit'],
    }),
    testNotificationChannel: builder.mutation<SettingsTestResult, SettingsChannel>({
      query: (channel) => ({ url: 'settings/notifications/test', method: 'POST', body: { channel } }),
      invalidatesTags: ['Audit'],
    }),
  }),
})

export const { useGetNotificationSettingsQuery, useUpdateNotificationSettingsMutation, useTestNotificationChannelMutation } = settingsApi
