import { baseApi } from '@/shared/api'

export type Channel = 'telegram' | 'email' | 'webhook' | 'extra'
export type DeliveryStatus = 'pending' | 'sending' | 'sent' | 'failed' | 'unknown'
export type Delivery = {
  id: number
  notification_type: 'payment.due_soon' | 'occurrence.paid' | 'occurrence.unpaid' | 'recurring.created' | 'recurring.stopped'
  occurrence_id: number | null
  channel: Channel
  status: DeliveryStatus
  attempts: number
  last_error: string | null
  sent_at: string | null
  created_at: string
}
export type DeliveryPage = { items: Delivery[]; total: number; limit: number; offset: number }
export type DeliveryParams = { limit: number; offset: number; occurrence_id?: number; channel?: Channel; status?: DeliveryStatus }

const deliveryApi = baseApi.injectEndpoints({
  endpoints: (builder) => ({
    getDeliveries: builder.query<DeliveryPage, DeliveryParams>({
      query: (params) => ({ url: 'notifications/deliveries', params }),
      providesTags: ['Deliveries'],
    }),
  }),
})

export const { useGetDeliveriesQuery } = deliveryApi
