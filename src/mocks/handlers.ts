import { http, HttpResponse } from 'msw'
import { demoState, demoTimestamp, demoToday, nextId, pageOf, totals } from './demoState'
import type { DemoAttachment, DemoOccurrence, DemoRecurring } from './demoState'

const api = '/api/v1'
const jsonError = (status: number, code: string, message: string) => HttpResponse.json({ error: { code, message } }, { status })
const requireUser = () => demoState.activeUser ? null : jsonError(401, 'unauthorized', 'Войдите снова')
const requireAdmin = () => requireUser() ?? (demoState.activeUser?.role === 'admin' ? null : jsonError(403, 'forbidden', 'Недостаточно прав'))
const ref = () => ({ id: demoState.activeUser!.id, login: demoState.activeUser!.login })
const idOf = (value: string | readonly string[] | undefined) => Number(value)
const dateRange = (url: URL) => ({ from: url.searchParams.get('from') ?? demoToday.slice(0, 7) + '-01', to: url.searchParams.get('to') ?? demoToday })
const matchingOccurrences = (from: string, to: string) => demoState.occurrences.filter((item) => item.due_date >= from && item.due_date <= to)
const publicAttachment = (item: DemoAttachment) => ({ id: item.id, occurrence_id: item.occurrence_id, kind: item.kind, url: item.url, title: item.title, file_name: item.file_name, content_type: item.content_type, size_bytes: item.size_bytes, created_at: item.created_at, created_by: item.created_by })

function assignmentOf(body: { assignee_ids?: number[]; assign_all?: boolean }) {
  const assignAll = body.assign_all === true
  const ids = assignAll ? [] : body.assignee_ids ?? []
  const assignees = demoState.users.filter(({ id, role }) => role === 'user' && ids.includes(id)).map(({ id, login }) => ({ id, login }))
  return { assign_all: assignAll, assignees }
}

/** Demo: a numeric value is an ID (linked), otherwise a username waiting for /start. */
function telegramOf(value: string | null | undefined) {
  const text = value?.trim() ?? ''
  if (!text) return { telegram_linked: false, telegram_username: null, telegram_user_id: null }
  if (/^\d+$/.test(text)) return { telegram_linked: true, telegram_username: null, telegram_user_id: Number(text) }
  return { telegram_linked: false, telegram_username: text.replace(/^@/, '').toLowerCase(), telegram_user_id: null }
}

// Demo: team applications for the supervisor (login «boss», empty team)
const demoApplications = [
  { id: 1, status: 'pending', team_name: 'Бета', admin_login: 'beta-admin', applicant: { telegram_id: 5001, username: 'beta_owner', name: 'Ольга' }, telegram_chat_id: '-1001234567890', smtp: null, created_at: demoTimestamp, decided_at: null as string | null, decided_by: null as string | null, reject_reason: null as string | null, team_id: null },
]

// Demo: notification settings of the admin tab
const demoSettings = {
  telegram_chat_id: '', telegram_bot_configured: true, telegram_bot_username: 'demo_bot',
  smtp_host: '', smtp_port: 587, smtp_user: '', smtp_password_set: false, smtp_from: '', smtp_security: 'starttls',
  email_recipients: [] as string[], webhook_url: '', webhook_secret_set: false,
  channels: { telegram: true, email: false, webhook: false },
  updated_at: null as string | null, updated_by: null as string | null, version: 0,
}

function audit(action: string, objectType: 'user' | 'recurring_payment' | 'payment_occurrence' | 'attachment', objectId: number) {
  demoState.audit.unshift({ id: nextId(demoState.audit), at: demoTimestamp, actor: ref(), source: 'web', action, object_type: objectType, object_id: objectId, result: 'success', details: {}, ip: null })
}

export const handlers = [
  http.get(`${api}/auth/me`, () => requireUser() ?? HttpResponse.json(demoState.activeUser)),
  http.post(`${api}/auth/login`, async ({ request }) => {
    const body = await request.json() as { team?: string; login?: string; password?: string }
    const user = demoState.users.find(({ login }) => login === body.login)
    if (!user || body.password !== 'demo') return jsonError(401, 'invalid_credentials', 'Проверьте логин и пароль')
    demoState.activeUser = user
    return HttpResponse.json({ user, session: { token: 'demo-only', expires_at: '2026-10-31T12:00:00+03:00' } })
  }),
  http.post(`${api}/auth/logout`, () => {
    const denied = requireUser()
    if (denied) return denied
    demoState.activeUser = null
    return new HttpResponse(null, { status: 204 })
  }),
  http.get(`${api}/config`, () => requireUser() ?? HttpResponse.json({
    team: { id: 1, name: 'demo' }, timezone_offset: '+03:00', timezone_label: 'GMT+3', today: demoToday, reminder_days_before: 3,
    currencies: ['RUB', 'USD', 'EUR'], periodicities: ['once', 'daily', 'weekly', 'monthly', 'every_n_days'], telegram_bot_username: null, miniapp_url: null,
    channels: { telegram: true, email: true, webhook: true, extra: true }, dev_mode: true,
  })),

  http.get(`${api}/payment-occurrences`, ({ request }) => {
    const denied = requireUser()
    if (denied) return denied
    const url = new URL(request.url)
    const query = (name: string) => url.searchParams.get(name)
    const assignee = Number(query('assignee_id'))
    const items = demoState.occurrences.filter((item) =>
      (!query('status') || item.status === query('status'))
      && (query('overdue') === null || item.is_overdue === (query('overdue') === 'true'))
      && (!query('due_from') || item.due_date >= query('due_from')!)
      && (!query('due_to') || item.due_date <= query('due_to')!)
      && (!query('recurring_payment_id') || item.recurring_payment_id === Number(query('recurring_payment_id')))
      && (!assignee || item.assign_all || item.assignees.some(({ id }) => id === assignee)))
    const sorted = [...items].sort((a, b) => query('sort') === 'due_date' ? a.due_date.localeCompare(b.due_date) : b.due_date.localeCompare(a.due_date))
    return HttpResponse.json(pageOf(sorted, url))
  }),
  http.get(`${api}/payment-occurrences/:id`, ({ params }) => {
    const denied = requireUser()
    if (denied) return denied
    const item = demoState.occurrences.find(({ id }) => id === idOf(params.id))
    return item ? HttpResponse.json(item) : jsonError(404, 'not_found', 'Период не найден')
  }),
  http.patch(`${api}/payment-occurrences/:id`, async ({ params, request }) => {
    const denied = requireUser()
    if (denied) return denied
    const item = demoState.occurrences.find(({ id }) => id === idOf(params.id))
    if (!item) return jsonError(404, 'not_found', 'Период не найден')
    const body = await request.json() as { status?: 'paid' | 'unpaid'; paid_date?: string; expected_version?: number }
    if (body.expected_version !== item.version) return jsonError(409, 'version_conflict', 'Период изменился')
    if (body.status === 'unpaid') {
      item.status = 'unpaid'; item.paid_date = null; item.paid_by = null; item.paid_via = null
    } else if (body.status === 'paid' || body.paid_date) {
      item.status = 'paid'; item.paid_date = body.paid_date ?? item.paid_date; item.paid_by = ref(); item.paid_via = 'web'
    }
    item.is_overdue = item.status === 'unpaid' && item.due_date < demoToday
    item.is_paid_late = item.status === 'paid' && !!item.paid_date && item.paid_date > item.due_date
    item.state = item.status === 'paid' ? (item.is_paid_late ? 'paid_late' : 'paid') : (item.is_overdue ? 'overdue' : 'upcoming')
    item.version += 1
    item.updated_at = demoTimestamp
    audit(item.status === 'paid' ? 'occurrence.paid' : 'occurrence.unpaid', 'payment_occurrence', item.id)
    return HttpResponse.json(item)
  }),
  http.get(`${api}/payments/summary`, ({ request }) => {
    const denied = requireUser()
    if (denied) return denied
    const { from, to } = dateRange(new URL(request.url))
    return HttpResponse.json({ from, to, today: demoToday, currencies: totals(matchingOccurrences(from, to)) })
  }),

  http.get(`${api}/recurring-payments`, ({ request }) => requireAdmin() ?? HttpResponse.json(pageOf(demoState.recurring, new URL(request.url)))),
  http.post(`${api}/recurring-payments`, async ({ request }) => {
    const denied = requireAdmin()
    if (denied) return denied
    const body = await request.json() as { title: string; amount: string; currency: DemoRecurring['currency']; periodicity: DemoRecurring['periodicity']; interval_days?: number; next_due_date: string; assignee_ids?: number[]; assign_all?: boolean }
    const item: DemoRecurring = { id: nextId(demoState.recurring), title: body.title, amount: body.amount, currency: body.currency, periodicity: body.periodicity, interval_days: body.interval_days ?? null, completed: false, anchor_day: Number(body.next_due_date.slice(-2)), first_due_date: body.next_due_date, next_due_date: body.next_due_date, status: 'active', created_at: demoTimestamp, stopped_at: null, created_by: ref(), ...assignmentOf(body), version: 1 }
    demoState.recurring.unshift(item)
    const occurrence: DemoOccurrence = { id: nextId(demoState.occurrences), recurring_payment_id: item.id, title: item.title, amount: item.amount, currency: item.currency, due_date: body.next_due_date, status: 'unpaid', paid_date: null, is_overdue: body.next_due_date < demoToday, is_paid_late: false, state: body.next_due_date < demoToday ? 'overdue' : 'upcoming', recurring_status: 'active', assign_all: item.assign_all, assignees: item.assignees, paid_by: null, paid_via: null, reminder_sent_at: null, attachments_count: 0, version: 1, created_at: demoTimestamp, updated_at: demoTimestamp }
    demoState.occurrences.unshift(occurrence)
    audit('recurring.create', 'recurring_payment', item.id)
    return HttpResponse.json(item, { status: 201 })
  }),
  http.patch(`${api}/recurring-payments/:id`, async ({ params, request }) => {
    const denied = requireAdmin()
    if (denied) return denied
    const item = demoState.recurring.find(({ id }) => id === idOf(params.id))
    if (!item) return jsonError(404, 'not_found', 'Платёж не найден')
    const body = await request.json() as Partial<Pick<DemoRecurring, 'title' | 'amount' | 'currency' | 'periodicity' | 'interval_days'>> & { next_due_date?: string; assignee_ids?: number[]; assign_all?: boolean; expected_version?: number }
    if (body.expected_version !== undefined && body.expected_version !== item.version) return jsonError(409, 'version_conflict', 'Запись изменена другим пользователем. Обновите данные')
    if (item.status !== 'active') return jsonError(422, 'validation_error', 'Прекращённый платёж нельзя изменить')
    const { assignee_ids, assign_all, next_due_date } = body
    for (const key of ['title', 'amount', 'currency', 'periodicity', 'interval_days'] as const) if (key in body) Object.assign(item, { [key]: body[key] })
    item.version += 1
    if (next_due_date) Object.assign(item, { next_due_date, first_due_date: next_due_date, anchor_day: Number(next_due_date.slice(-2)) })
    if (assignee_ids !== undefined || assign_all !== undefined) Object.assign(item, assignmentOf({ assignee_ids, assign_all }))
    demoState.occurrences
      .filter(({ recurring_payment_id, status, due_date }) => recurring_payment_id === item.id && status === 'unpaid' && due_date >= demoToday)
      .forEach((occurrence) => Object.assign(occurrence, { title: item.title, amount: item.amount, currency: item.currency, assign_all: item.assign_all, assignees: item.assignees }, next_due_date ? { due_date: next_due_date } : {}))
    audit('recurring.update', 'recurring_payment', item.id)
    return HttpResponse.json(item)
  }),
  http.delete(`${api}/recurring-payments/:id`, ({ params }) => {
    const denied = requireAdmin()
    if (denied) return denied
    const item = demoState.recurring.find(({ id }) => id === idOf(params.id))
    if (!item) return jsonError(404, 'not_found', 'Платёж не найден')
    item.status = 'stopped'; item.stopped_at = demoTimestamp; item.next_due_date = null; item.version += 1
    demoState.occurrences.filter(({ recurring_payment_id }) => recurring_payment_id === item.id).forEach((occurrence) => { occurrence.recurring_status = 'stopped' })
    audit('recurring.stop', 'recurring_payment', item.id)
    return HttpResponse.json(item)
  }),

  http.get(`${api}/users`, ({ request }) => requireAdmin() ?? HttpResponse.json(pageOf(demoState.users.filter(({ role }) => role === 'user'), new URL(request.url)))),
  http.post(`${api}/users`, async ({ request }) => {
    const denied = requireAdmin()
    if (denied) return denied
    const body = await request.json() as { login: string; password: string; telegram?: string }
    if (demoState.users.some(({ login }) => login === body.login)) return jsonError(409, 'login_taken', 'Логин занят')
    const user = { id: nextId(demoState.users), login: body.login, role: 'user' as const, is_protected: false, ...telegramOf(body.telegram), created_at: demoTimestamp, updated_at: demoTimestamp }
    demoState.users.push(user)
    audit('user.created', 'user', user.id)
    return HttpResponse.json(user, { status: 201 })
  }),
  http.patch(`${api}/users/:id`, async ({ params, request }) => {
    const denied = requireAdmin()
    if (denied) return denied
    const user = demoState.users.find(({ id, role }) => id === idOf(params.id) && role === 'user')
    if (!user) return jsonError(404, 'not_found', 'Пользователь не найден')
    const body = await request.json() as { telegram?: string | null; password?: string }
    if ('telegram' in body) Object.assign(user, telegramOf(body.telegram))
    if (body.password) user.must_change_password = true
    audit('user.update', 'user', user.id)
    return HttpResponse.json(user)
  }),
  http.delete(`${api}/users/:id`, ({ params }) => {
    const denied = requireAdmin()
    if (denied) return denied
    const index = demoState.users.findIndex(({ id, role }) => id === idOf(params.id) && role === 'user')
    if (index < 0) return jsonError(404, 'not_found', 'Пользователь не найден')
    const [user] = demoState.users.splice(index, 1)
    if (!user) return jsonError(404, 'not_found', 'Пользователь не найден')
    audit('user.deleted', 'user', user.id)
    return new HttpResponse(null, { status: 204 })
  }),

  http.get(`${api}/calendar/export`, ({ request }) => {
    const denied = requireUser()
    if (denied) return denied
    const url = new URL(request.url)
    const format = url.searchParams.get('format') === 'ics' ? 'ics' : 'csv'
    const from = url.searchParams.get('from') ?? demoToday
    const to = url.searchParams.get('to') ?? demoToday
    const items = matchingOccurrences(from, to)
    const body = format === 'csv'
      ? '\ufeffДата;Платёж;Сумма;Валюта;Статус\r\n' + items.map((item) => [item.due_date, item.title, item.amount.replace('.', ','), item.currency, item.state].join(';')).join('\r\n')
      : ['BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//Aeza PayKeep//demo//RU', ...items.flatMap((item) => ['BEGIN:VEVENT', `UID:demo-${item.id}@invoice-keeper`, `DTSTART;VALUE=DATE:${item.due_date.split('-').join('')}`, `SUMMARY:${item.title} — ${item.amount} ${item.currency}`, 'END:VEVENT']), 'END:VCALENDAR'].join('\r\n')
    return new HttpResponse(body, { headers: { 'Content-Type': format === 'csv' ? 'text/csv; charset=utf-8' : 'text/calendar; charset=utf-8', 'Content-Disposition': `attachment; filename="calendar-demo-${from}-${to}.${format}"` } })
  }),
  http.get(`${api}/calendar`, ({ request }) => {
    const denied = requireUser()
    if (denied) return denied
    const month = new URL(request.url).searchParams.get('month') ?? demoToday.slice(0, 7)
    const monthly = demoState.occurrences.filter(({ due_date }) => due_date.startsWith(month))
    const days = [...new Set(monthly.map(({ due_date }) => due_date))].sort().map((date) => {
      const matching = monthly.filter(({ due_date }) => due_date === date)
      return { date, items: matching.map((item) => ({ occurrence_id: item.id, recurring_payment_id: item.recurring_payment_id, title: item.title, amount: item.amount, currency: item.currency, due_date: item.due_date, state: item.state, is_projected: false })), totals: totals(matching) }
    })
    return HttpResponse.json({ month, today: demoToday, days, month_totals: totals(monthly) })
  }),
  http.get(`${api}/budget`, ({ request }) => {
    const denied = requireUser()
    if (denied) return denied
    const url = new URL(request.url)
    const period = url.searchParams.get('period') === 'year' ? 'year' : 'month'
    const year = Number(url.searchParams.get('year')) || Number(demoToday.slice(0, 4))
    const month = Number(url.searchParams.get('month')) || Number(demoToday.slice(5, 7))
    const from = period === 'year' ? `${year}-01-01` : `${year}-${String(month).padStart(2, '0')}-01`
    const to = period === 'year' ? `${year}-12-31` : `${year}-${String(month).padStart(2, '0')}-${new Date(Date.UTC(year, month, 0)).getUTCDate()}`
    const currencies = totals(matchingOccurrences(from, to)).map((entry) => ({ currency: entry.currency, planned: entry.total, existing_paid: entry.paid, existing_unpaid: entry.unpaid, projected: '0.00' }))
    return HttpResponse.json({ period, from, to, currencies })
  }),

  http.get(`${api}/payment-occurrences/:id/attachments`, ({ params }) => requireUser() ?? HttpResponse.json(demoState.attachments.filter(({ occurrence_id }) => occurrence_id === idOf(params.id)).map(publicAttachment))),
  http.post(`${api}/payment-occurrences/:id/attachments`, async ({ params, request }) => {
    const denied = requireUser()
    if (denied) return denied
    const occurrence = demoState.occurrences.find(({ id }) => id === idOf(params.id))
    if (!occurrence) return jsonError(404, 'not_found', 'Период не найден')
    if (occurrence.attachments_count >= 5) return jsonError(409, 'attachment_limit', 'Лимит вложений')
    let attachment: DemoAttachment & { file?: File }
    if (request.headers.get('content-type')?.includes('multipart/form-data')) {
      const data = await request.formData()
      const file = data.get('file')
      if (!(file instanceof File)) return jsonError(422, 'validation_error', 'Выберите файл')
      attachment = { id: nextId(demoState.attachments), occurrence_id: occurrence.id, kind: 'file', url: null, title: null, file_name: file.name, content_type: file.type as DemoAttachment['content_type'], size_bytes: file.size, created_at: demoTimestamp, created_by: ref(), file }
    } else {
      const body = await request.json() as { url: string; title: string | null }
      attachment = { id: nextId(demoState.attachments), occurrence_id: occurrence.id, kind: 'link', url: body.url, title: body.title, file_name: null, content_type: null, size_bytes: null, created_at: demoTimestamp, created_by: ref() }
    }
    demoState.attachments.push(attachment)
    occurrence.attachments_count += 1
    audit('attachment.created', 'attachment', attachment.id)
    return HttpResponse.json(publicAttachment(attachment), { status: 201 })
  }),
  http.get(`${api}/attachments/:id/file`, async ({ params }) => {
    const denied = requireUser()
    if (denied) return denied
    const attachment = demoState.attachments.find(({ id }) => id === idOf(params.id))
    if (!attachment?.file) return jsonError(404, 'not_found', 'Файл не найден')
    return new HttpResponse(await attachment.file.arrayBuffer(), { headers: { 'Content-Type': attachment.content_type ?? 'application/octet-stream' } })
  }),
  http.delete(`${api}/attachments/:id`, ({ params }) => {
    const denied = requireUser()
    if (denied) return denied
    const index = demoState.attachments.findIndex(({ id }) => id === idOf(params.id))
    if (index < 0) return jsonError(404, 'not_found', 'Вложение не найдено')
    const [attachment] = demoState.attachments.splice(index, 1)
    if (!attachment) return jsonError(404, 'not_found', 'Вложение не найдено')
    const occurrence = demoState.occurrences.find(({ id }) => id === attachment.occurrence_id)
    if (occurrence) occurrence.attachments_count -= 1
    audit('attachment.deleted', 'attachment', attachment.id)
    return new HttpResponse(null, { status: 204 })
  }),

  http.get(`${api}/audit-log`, ({ request }) => {
    const denied = requireAdmin()
    if (denied) return denied
    const url = new URL(request.url)
    const action = url.searchParams.get('action')
    const actorId = url.searchParams.get('actor_id')
    const from = url.searchParams.get('from')
    const to = url.searchParams.get('to')
    const recurringId = Number(url.searchParams.get('recurring_payment_id'))
    const periodIds = new Set(demoState.occurrences.filter(({ recurring_payment_id }) => recurring_payment_id === recurringId).map(({ id }) => id))
    const ofPayment = (item: { object_type: string | null; object_id: number | null }) => !recurringId
      || (item.object_type === 'recurring_payment' && item.object_id === recurringId)
      || (item.object_type === 'payment_occurrence' && item.object_id !== null && periodIds.has(item.object_id))
    const items = demoState.audit.filter((item) => (!action || item.action === action) && (!actorId || item.actor?.id === Number(actorId)) && (!from || item.at.slice(0, 10) >= from) && (!to || item.at.slice(0, 10) <= to) && ofPayment(item))
    return HttpResponse.json(pageOf(items, url))
  }),
  http.get(`${api}/supervisor/applications`, ({ request }) => {
    if (demoState.activeUser?.role !== 'supervisor') return jsonError(403, 'forbidden', 'Недостаточно прав')
    const url = new URL(request.url)
    const status = url.searchParams.get('status') ?? 'pending'
    return HttpResponse.json(pageOf(demoApplications.filter((item) => status === 'all' || item.status === status), url))
  }),
  http.post(`${api}/supervisor/applications/:id/:decision`, async ({ params, request }) => {
    if (demoState.activeUser?.role !== 'supervisor') return jsonError(403, 'forbidden', 'Недостаточно прав')
    const item = demoApplications.find(({ id }) => id === idOf(params.id))
    if (!item) return jsonError(404, 'not_found', 'Заявка не найдена')
    if (item.status !== 'pending') return jsonError(409, 'application_decided', 'По заявке уже принято решение')
    const approved = params.decision === 'approve'
    const reason = approved ? null : (await request.json() as { reason: string }).reason
    Object.assign(item, { status: approved ? 'approved' : 'rejected', decided_at: demoTimestamp, decided_by: demoState.activeUser.login, reject_reason: reason })
    return HttpResponse.json({ application: item, notified: false, temp_password: approved ? 'demo-temp-pass' : null })
  }),
  http.get(`${api}/settings/notifications`, () => requireAdmin() ?? HttpResponse.json(demoSettings)),
  http.patch(`${api}/settings/notifications`, async ({ request }) => {
    const denied = requireAdmin()
    if (denied) return denied
    const body = await request.json() as Record<string, unknown> & { expected_version?: number; smtp_password?: string; webhook_secret?: string }
    if (body.expected_version !== undefined && body.expected_version !== demoSettings.version) return jsonError(409, 'version_conflict', 'Настройки уже изменили')
    const password = body.smtp_password
    const secret = body.webhook_secret
    const rest: Record<string, unknown> = { ...body }
    for (const key of ['expected_version', 'smtp_password', 'webhook_secret']) delete rest[key]
    Object.assign(demoSettings, rest, { version: demoSettings.version + 1, updated_at: demoTimestamp, updated_by: demoState.activeUser?.login ?? null })
    if (password !== undefined) demoSettings.smtp_password_set = password !== ''
    if (secret !== undefined) demoSettings.webhook_secret_set = secret !== ''
    demoSettings.channels = { telegram: demoSettings.telegram_bot_configured, email: Boolean(demoSettings.smtp_host && demoSettings.email_recipients.length), webhook: Boolean(demoSettings.webhook_url) }
    audit('settings.update', 'user', demoState.activeUser?.id ?? 1)
    return HttpResponse.json(demoSettings)
  }),
  http.post(`${api}/settings/notifications/test`, async ({ request }) => {
    const denied = requireAdmin()
    if (denied) return denied
    const { channel } = await request.json() as { channel: 'telegram' | 'email' | 'webhook' }
    const ok = demoSettings.channels[channel]
    return HttpResponse.json({ channel, ok, error: ok ? null : 'Канал не настроен (демо)' })
  }),
  http.get(`${api}/notifications/deliveries`, ({ request }) => {
    const denied = requireAdmin()
    if (denied) return denied
    const url = new URL(request.url)
    const channel = url.searchParams.get('channel')
    const status = url.searchParams.get('status')
    const occurrenceId = url.searchParams.get('occurrence_id')
    const items = demoState.deliveries.filter((item) => (!channel || item.channel === channel) && (!status || item.status === status) && (!occurrenceId || item.occurrence_id === Number(occurrenceId)))
    return HttpResponse.json(pageOf(items, url))
  }),

  http.all(`${api}/*`, () => jsonError(501, 'demo_not_implemented', 'Этот запрос не входит в демо')),
]
