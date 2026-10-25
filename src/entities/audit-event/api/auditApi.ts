import { baseApi } from '@/shared/api'

export type AuditEvent = {
  id: number
  at: string
  actor: { id: number; login: string } | null
  source: 'web' | 'telegram' | 'system'
  action: string
  object_type: 'user' | 'recurring_payment' | 'payment_occurrence' | 'attachment' | 'notification' | 'personal_reminder' | 'team_application' | null
  object_id: number | null
  result: 'success' | 'failure'
  details: Record<string, unknown>
  ip: string | null
}

export type AuditEventPage = { items: AuditEvent[]; total: number; limit: number; offset: number }
export type AuditParams = { limit: number; offset: number; action?: string; actor_id?: number; recurring_payment_id?: number; from?: string; to?: string }

const auditApi = baseApi.injectEndpoints({
  endpoints: (builder) => ({
    getAuditEvents: builder.query<AuditEventPage, AuditParams>({
      query: (params) => ({ url: 'audit-log', params }),
      providesTags: ['Audit'],
    }),
  }),
})

export const { useGetAuditEventsQuery } = auditApi
