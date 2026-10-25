// Изолированные демонстрационные данные. Этот модуль импортируется только в dev:demo.
export type DemoUser = {
  id: number
  login: string
  role: 'admin' | 'user' | 'supervisor'
  is_protected: boolean
  must_change_password?: boolean
  totp_enabled: boolean
  telegram_linked: boolean
  telegram_dm_enabled: boolean
  telegram_dm_days_before: number
  telegram_username?: string | null
  telegram_user_id?: number | null
  created_at: string
  updated_at: string
}
export type DemoOccurrence = {
  id: number
  recurring_payment_id: number
  title: string
  amount: string
  currency: 'RUB' | 'USD' | 'EUR'
  due_date: string
  status: 'paid' | 'unpaid'
  paid_date: string | null
  is_overdue: boolean
  is_paid_late: boolean
  state: 'upcoming' | 'overdue' | 'paid' | 'paid_late'
  recurring_status: 'active' | 'stopped'
  assign_all: boolean
  assignees: { id: number; login: string }[]
  paid_by: { id: number; login: string } | null
  paid_via: 'web' | 'telegram' | null
  reminder_sent_at: string | null
  attachments_count: number
  version: number
  created_at: string
  updated_at: string
}
export type DemoRecurring = {
  id: number
  title: string
  amount: string
  currency: DemoOccurrence['currency']
  periodicity: 'once' | 'daily' | 'weekly' | 'monthly' | 'every_n_days'
  interval_days?: number | null
  completed?: boolean
  anchor_day: number
  first_due_date: string
  next_due_date: string | null
  status: 'active' | 'stopped'
  created_at: string
  stopped_at: string | null
  created_by: { id: number; login: string }
  assign_all: boolean
  assignees: { id: number; login: string }[]
  version: number
}
export type DemoAttachment = {
  id: number
  occurrence_id: number
  kind: 'file' | 'link'
  url: string | null
  title: string | null
  file_name: string | null
  content_type: 'image/jpeg' | 'image/png' | 'application/pdf' | null
  size_bytes: number | null
  created_at: string
  created_by: { id: number; login: string }
}

export const demoToday = '2026-10-24'
export const demoTimestamp = '2026-10-24T12:00:00+03:00'
const admin: DemoUser = { id: 1, login: 'admin', role: 'admin', is_protected: true, totp_enabled: false, telegram_linked: false, telegram_dm_enabled: true, telegram_dm_days_before: 3, created_at: demoTimestamp, updated_at: demoTimestamp }
const anna: DemoUser = { id: 2, login: 'anna', role: 'user', is_protected: false, totp_enabled: false, telegram_linked: false, telegram_dm_enabled: true, telegram_dm_days_before: 3, created_at: demoTimestamp, updated_at: demoTimestamp }
const boss: DemoUser = { id: 3, login: 'boss', role: 'supervisor', is_protected: true, totp_enabled: false, telegram_linked: false, telegram_dm_enabled: true, telegram_dm_days_before: 3, created_at: demoTimestamp, updated_at: demoTimestamp }

export const demoState = {
  activeUser: null as DemoUser | null,
  users: [admin, anna, boss] as DemoUser[],
  recurring: [
    { id: 7, title: 'Хостинг проекта', amount: '4500.00', currency: 'RUB', periodicity: 'monthly', anchor_day: 20, first_due_date: '2026-09-20', next_due_date: '2026-11-20', status: 'active', created_at: demoTimestamp, stopped_at: null, created_by: { id: 1, login: 'admin' }, assign_all: false, assignees: [{ id: 2, login: 'anna' }], version: 1 },
    { id: 8, title: 'Облачное хранилище', amount: '120.00', currency: 'USD', periodicity: 'monthly', anchor_day: 28, first_due_date: '2026-09-28', next_due_date: '2026-10-28', status: 'active', created_at: demoTimestamp, stopped_at: null, created_by: { id: 1, login: 'admin' }, assign_all: true, assignees: [], version: 1 },
    { id: 9, title: 'Дизайн-сервис', amount: '35.00', currency: 'EUR', periodicity: 'monthly', anchor_day: 15, first_due_date: '2026-10-15', next_due_date: '2026-11-15', status: 'active', created_at: demoTimestamp, stopped_at: null, created_by: { id: 1, login: 'admin' }, assign_all: false, assignees: [], version: 1 },
  ] as DemoRecurring[],
  occurrences: [
    { id: 101, recurring_payment_id: 7, title: 'Хостинг проекта', amount: '4500.00', currency: 'RUB', due_date: '2026-10-20', status: 'unpaid', paid_date: null, is_overdue: true, is_paid_late: false, state: 'overdue', recurring_status: 'active', assign_all: false, assignees: [{ id: 2, login: 'anna' }], paid_by: null, paid_via: null, reminder_sent_at: '2026-10-17T10:00:00+03:00', attachments_count: 0, version: 1, created_at: demoTimestamp, updated_at: demoTimestamp },
    { id: 102, recurring_payment_id: 8, title: 'Облачное хранилище', amount: '120.00', currency: 'USD', due_date: '2026-10-28', status: 'unpaid', paid_date: null, is_overdue: false, is_paid_late: false, state: 'upcoming', recurring_status: 'active', assign_all: true, assignees: [], paid_by: null, paid_via: null, reminder_sent_at: null, attachments_count: 0, version: 1, created_at: demoTimestamp, updated_at: demoTimestamp },
    { id: 103, recurring_payment_id: 9, title: 'Дизайн-сервис', amount: '35.00', currency: 'EUR', due_date: '2026-10-15', status: 'paid', paid_date: '2026-10-15', is_overdue: false, is_paid_late: false, state: 'paid', recurring_status: 'active', assign_all: false, assignees: [], paid_by: { id: 2, login: 'anna' }, paid_via: 'web', reminder_sent_at: null, attachments_count: 0, version: 1, created_at: demoTimestamp, updated_at: demoTimestamp },
    { id: 104, recurring_payment_id: 8, title: 'Облачное хранилище', amount: '120.00', currency: 'USD', due_date: '2026-09-28', status: 'paid', paid_date: '2026-10-02', is_overdue: false, is_paid_late: true, state: 'paid_late', recurring_status: 'active', assign_all: true, assignees: [], paid_by: { id: 2, login: 'anna' }, paid_via: 'web', reminder_sent_at: null, attachments_count: 0, version: 1, created_at: demoTimestamp, updated_at: demoTimestamp },
  ] as DemoOccurrence[],
  attachments: [] as (DemoAttachment & { file?: File })[],
  audit: [
    { id: 1, at: demoTimestamp, actor: { id: 1, login: 'admin' }, source: 'web', action: 'recurring.created', object_type: 'recurring_payment', object_id: 7, result: 'success', details: {}, ip: null },
    { id: 2, at: demoTimestamp, actor: { id: 2, login: 'anna' }, source: 'web', action: 'occurrence.paid', object_type: 'payment_occurrence', object_id: 103, result: 'success', details: {}, ip: null },
  ],
  deliveries: [
    { id: 1, notification_type: 'payment.due_soon', occurrence_id: 101, channel: 'telegram', status: 'sent', attempts: 1, last_error: null, sent_at: '2026-10-17T10:00:00+03:00', created_at: '2026-10-17T10:00:00+03:00' },
    { id: 2, notification_type: 'payment.due_soon', occurrence_id: 101, channel: 'email', status: 'failed', attempts: 2, last_error: 'Демонстрационная ошибка доставки', sent_at: null, created_at: demoTimestamp },
  ],
}

export function nextId(items: { id: number }[]): number {
  return Math.max(0, ...items.map(({ id }) => id)) + 1
}

export function pageOf<T>(items: T[], url: URL): { items: T[]; total: number; limit: number; offset: number } {
  const limit = Math.min(100, Math.max(1, Number(url.searchParams.get('limit')) || 50))
  const offset = Math.max(0, Number(url.searchParams.get('offset')) || 0)
  return { items: items.slice(offset, offset + limit), total: items.length, limit, offset }
}

const currencies = ['RUB', 'USD', 'EUR'] as const
const toCents = (amount: string): bigint => {
  const [whole = '0', fraction = ''] = amount.split('.')
  return BigInt(whole) * 100n + BigInt(fraction.padEnd(2, '0').slice(0, 2))
}
const fromCents = (amount: bigint): string => `${amount / 100n}.${String(amount % 100n).padStart(2, '0')}`

export function totals(items: DemoOccurrence[]) {
  return currencies.map((currency) => {
    const matching = items.filter((item) => item.currency === currency)
    const total = matching.reduce((sum, item) => sum + toCents(item.amount), 0n)
    const paid = matching.filter((item) => item.status === 'paid').reduce((sum, item) => sum + toCents(item.amount), 0n)
    const overdue = matching.filter((item) => item.is_overdue).reduce((sum, item) => sum + toCents(item.amount), 0n)
    return { currency, total: fromCents(total), paid: fromCents(paid), unpaid: fromCents(total - paid), overdue: fromCents(overdue), count: matching.length }
  })
}
