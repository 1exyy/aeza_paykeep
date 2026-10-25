import { baseApi } from '@/shared/api'
import type { Currency } from '@/shared/lib/money'
import type { OccurrenceState } from '../model/displayStatus'
import type { CurrencyTotals } from './summaryApi'

export type CalendarItem = {
  occurrence_id: number | null
  recurring_payment_id: number
  title: string
  amount: string
  currency: Currency
  due_date: string
  state: OccurrenceState | null
  is_projected: boolean
}
export type CalendarDay = { date: string; items: CalendarItem[]; totals: CurrencyTotals[] }
export type CalendarMonth = { month: string; today: string; days: CalendarDay[]; month_totals: CurrencyTotals[] }

/** The team's calendar as a file; the result is an object URL and a file name. */
export type CalendarExportParams = { format: 'csv' | 'ics'; from: string; to: string }
export type CalendarExportFile = { url: string; fileName: string }

function fileNameOf(response: Response, fallback: string): string {
  const header = response.headers.get('content-disposition') ?? ''
  const encoded = /filename\*=UTF-8''([^;]+)/i.exec(header)?.[1]
  if (encoded) {
    try {
      return decodeURIComponent(encoded)
    } catch {
      // a broken header: use the plain name below
    }
  }
  return /filename="([^"]+)"/i.exec(header)?.[1] ?? fallback
}

const calendarApi = baseApi.injectEndpoints({
  endpoints: (builder) => ({
    getCalendar: builder.query<CalendarMonth, string>({
      query: (month) => ({ url: 'calendar', params: { month } }),
      providesTags: ['Calendar'],
    }),
    exportCalendar: builder.mutation<CalendarExportFile, CalendarExportParams>({
      query: (params) => ({
        url: 'calendar/export',
        params,
        responseHandler: async (response: Response) => response.ok
          ? { url: URL.createObjectURL(await response.blob()), fileName: fileNameOf(response, `calendar.${params.format}`) }
          : response.json(),
      }),
    }),
  }),
})

export const { useGetCalendarQuery, useExportCalendarMutation } = calendarApi
