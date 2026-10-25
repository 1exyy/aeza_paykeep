import { baseApi } from '@/shared/api'

export type ApplicationStatus = 'pending' | 'approved' | 'rejected'

export type TeamApplication = {
  id: number
  status: ApplicationStatus
  team_name: string
  admin_login: string
  applicant: { telegram_id: number; username: string | null; name: string | null }
  telegram_chat_id: string
  smtp: { host: string; port: number; security: 'starttls' | 'ssl' | 'none'; user: string; password_set: boolean; from: string; recipients: string[] } | null
  created_at: string
  decided_at: string | null
  decided_by: string | null
  reject_reason: string | null
  team_id: number | null
}

export type TeamApplicationPage = { items: TeamApplication[]; total: number; limit: number; offset: number }
/** `temp_password` comes only when the application bot could not deliver it. */
export type ApplicationDecision = { application: TeamApplication; notified: boolean; temp_password: string | null }

const applicationsApi = baseApi.injectEndpoints({
  endpoints: (builder) => ({
    getApplications: builder.query<TeamApplicationPage, { status: ApplicationStatus | 'all'; limit: number; offset: number }>({
      query: (params) => ({ url: 'supervisor/applications', params }),
      providesTags: ['Applications'],
    }),
    approveApplication: builder.mutation<ApplicationDecision, number>({
      query: (id) => ({ url: `supervisor/applications/${id}/approve`, method: 'POST' }),
      invalidatesTags: (_result, error) => error ? [] : ['Applications'],
    }),
    rejectApplication: builder.mutation<ApplicationDecision, { id: number; reason: string }>({
      query: ({ id, reason }) => ({ url: `supervisor/applications/${id}/reject`, method: 'POST', body: { reason } }),
      invalidatesTags: (_result, error) => error ? [] : ['Applications'],
    }),
  }),
})

export const { useGetApplicationsQuery, useApproveApplicationMutation, useRejectApplicationMutation } = applicationsApi
