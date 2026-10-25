import { baseApi } from '@/shared/api'
import type { Currency } from '@/shared/lib/money'

// Поля GET /config из OpenAPI v1.0.0. Запрос запускать после проверки /auth/me.
export type AppConfig = {
  /** The team of the signed-in user. */
  team?: { id: number; name: string }
  timezone_offset: string
  timezone_label: string
  today: string
  reminder_days_before: number
  currencies: Currency[]
  periodicities: ('once' | 'daily' | 'weekly' | 'monthly' | 'every_n_days')[]
  telegram_bot_username: string | null
  miniapp_url: string | null
  channels: { telegram: boolean; email: boolean; webhook: boolean; extra: boolean }
  dev_mode: boolean
}

const configApi = baseApi.injectEndpoints({
  endpoints: (builder) => ({
    getConfig: builder.query<AppConfig, void>({ query: () => 'config', providesTags: ['Config'] }),
  }),
})

export const { useGetConfigQuery } = configApi
