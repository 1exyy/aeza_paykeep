import { expect, test } from '@playwright/test'

test.beforeEach(async ({ page }) => {
  await page.route('https://telegram.org/js/telegram-web-app.js?64', (route) => route.fulfill({ body: '' }))
  await page.route('**/api/v1/payments/summary?**', (route) => {
    const params = new URL(route.request().url()).searchParams
    const zero = (currency: string) => ({ currency, total: '0.00', paid: '0.00', unpaid: '0.00', overdue: '0.00', count: 0 })
    return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ from: params.get('from'), to: params.get('to'), today: '2026-10-24', currencies: [zero('RUB'), zero('USD'), zero('EUR')] }) })
  })
})

for (const width of [320, 375, 430]) {
  test(`оболочка не выходит за ширину ${width} px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 740 })
    await page.goto('/_dev/ui')
    await expect(page.getByRole('heading', { name: 'Общие компоненты' })).toBeVisible()
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width)
    if (width === 320) {
      await page.screenshot({ path: 'test-results/dev-ui-320.png', fullPage: true })
      await page.locator('article').first().screenshot({ path: 'test-results/payment-card-320.png' })
      await page.getByRole('region', { name: 'Сводка' }).screenshot({ path: 'test-results/summary-320.png' })
    }

    const field = page.getByRole('textbox', { name: 'Пример поля' })
    await field.focus()
    await expect(field).toBeFocused()
    await page.getByRole('button', { name: 'Проверить кнопку' }).click()
    await expect(page.getByRole('status').filter({ hasText: 'Нажатий: 1' })).toBeVisible()
  })
}

test('периоды и статусы в карточках различимы', async ({ page }) => {
  await page.goto('/_dev/ui')
  await expect(page.getByRole('article')).toHaveCount(4)
  await expect(page.getByText('Хранилище')).toHaveCount(2)
  await expect(page.getByText('30.09.2026')).toBeVisible()
  await expect(page.getByText('31.08.2026')).toBeVisible()
  await expect(page.getByRole('article').filter({ hasText: '30.09.2026' }).getByText('Просрочено', { exact: true })).toBeVisible()
  await expect(page.getByText('Оплачено с опозданием', { exact: true })).toBeVisible()
  await expect(page.getByText('12 345 678 901 234 567 890,12 RUB')).toBeVisible()
})

test('пустая выборка, ошибка и отказ в доступе имеют разные сообщения', async ({ page }) => {
  await page.goto('/_dev/ui')
  await expect(page.getByRole('heading', { name: 'Нет данных' })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Не удалось загрузить данные' })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Нет доступа' })).toBeVisible()
})

test('форма входа проверяет ввод и не создаёт сессию в dev-просмотре', async ({ page }) => {
  await page.goto('/_dev/ui')
  const form = page.getByRole('heading', { name: 'Форма входа — только оформление' }).locator('..')
  await form.getByRole('button', { name: 'Войти' }).click()
  await expect(form.getByText('Введите логин')).toBeVisible()
  await expect(form.getByText('Введите пароль')).toBeVisible()
  await form.getByRole('textbox', { name: 'Команда' }).fill('aeza')
  await form.getByRole('textbox', { name: 'Логин' }).fill('a')
  await form.getByLabel('Пароль').fill('x')
  await form.getByRole('button', { name: 'Войти' }).click()
  await expect(form.getByRole('status')).toHaveText('Форма проверена. Запрос не отправлялся.')
  await expect(page).toHaveURL(/\/_dev\/ui$/)
})

test('выбор валюты меняет только сводку', async ({ page }) => {
  await page.goto('/_dev/ui')
  const summary = page.getByRole('region', { name: 'Сводка' })
  await expect(summary.getByRole('button', { name: 'RUB' })).toHaveAttribute('aria-pressed', 'true')
  await summary.getByRole('button', { name: 'USD' }).click()
  await expect(summary.getByRole('button', { name: 'USD' })).toHaveAttribute('aria-pressed', 'true')
  await expect(summary.getByText('50,00 USD', { exact: true })).toBeVisible()
  await expect(page.getByRole('article')).toHaveCount(4)
})

test('защищённый адрес показывает вход без данных при 401', async ({ page }) => {
  await page.route('**/api/v1/auth/me', (route) => route.fulfill({ status: 401, contentType: 'application/json', body: JSON.stringify({ error: { code: 'unauthorized', message: 'Войдите снова' } }) }))
  await page.setViewportSize({ width: 320, height: 740 })
  await page.goto('/payments')
  await expect(page.getByRole('heading', { name: 'Вход', exact: true })).toBeVisible()
  await expect(page.getByRole('article')).toHaveCount(0)
  await page.screenshot({ path: 'test-results/login-320.png', fullPage: true })
})

test('контрактный вход показывает периоды и серверную зону, затем выход очищает экран', async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 740 })
  let authenticated = false
  const user = { id: 2, login: 'anna', role: 'user', is_protected: false, telegram_linked: false, created_at: '2026-10-24T09:00:00+05:00', updated_at: '2026-10-24T09:00:00+05:00' }
  const occurrence = { id: 42, recurring_payment_id: 7, title: 'Сервер', amount: '120.00', currency: 'USD', due_date: '2026-09-10', status: 'unpaid', paid_date: null, is_overdue: true, is_paid_late: false, state: 'overdue', recurring_status: 'active', assign_all: false, assignees: [], paid_by: null, paid_via: null, reminder_sent_at: null, attachments_count: 0, version: 1, created_at: '2026-10-24T09:00:00+05:00', updated_at: '2026-10-24T09:00:00+05:00' }
  await page.route('**/api/v1/auth/me', (route) => route.fulfill(authenticated
    ? { status: 200, contentType: 'application/json', body: JSON.stringify(user) }
    : { status: 401, contentType: 'application/json', body: JSON.stringify({ error: { code: 'unauthorized', message: 'Войдите снова' } }) }))
  await page.route('**/api/v1/auth/login', (route) => {
    authenticated = true
    return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ user, session: { token: 'test-token', expires_at: '2026-10-31T09:00:00+05:00' } }) })
  })
  await page.route('**/api/v1/auth/logout', (route) => {
    authenticated = false
    return route.fulfill({ status: 204 })
  })
  await page.route('**/api/v1/config', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ timezone_offset: '+05:00', timezone_label: 'GMT+5', today: '2026-10-24', reminder_days_before: 4, currencies: ['RUB', 'USD', 'EUR'], periodicities: ['monthly'], telegram_bot_username: null, miniapp_url: null, channels: { telegram: true, email: false, webhook: false, extra: false }, dev_mode: false }) }))
  await page.route('**/api/v1/payment-occurrences?**', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ items: [occurrence], total: 1, limit: 50, offset: 0 }) }))
  await page.route('**/api/v1/payment-occurrences/42', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(occurrence) }))
  await page.route('**/api/v1/payment-occurrences/42/attachments', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: '[]' }))
  await page.goto('/payments')
  await page.getByRole('textbox', { name: 'Команда' }).fill('aeza')
  await page.getByRole('textbox', { name: 'Логин' }).fill('anna')
  await page.getByLabel('Пароль').fill('example-password')
  await page.getByRole('button', { name: 'Войти' }).click()
  await expect(page.getByRole('heading', { name: 'Платежи', exact: true })).toBeVisible()
  await expect(page.getByText('Даты — GMT+5', { exact: true })).toBeVisible()
  await expect(page.getByRole('article').getByText('Просрочено')).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(375)
  await page.screenshot({ path: 'test-results/payments-contract-375.png', fullPage: true })
  await page.getByRole('link', { name: 'Открыть платёж' }).click()
  await expect(page.getByRole('heading', { name: 'Сервер' })).toBeVisible()
  await expect(page.getByText('Даты — GMT+5 (UTC+05:00). Настройка напоминаний: за 4 дня до срока.')).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Вложений пока нет' })).toBeVisible()
  await page.screenshot({ path: 'test-results/payment-details-contract-375.png', fullPage: true })
  await page.getByRole('button', { name: 'Ещё' }).click()
  await expect(page.getByRole('dialog', { name: 'Ещё' }).getByRole('link', { name: 'Сменить пароль' })).toBeVisible()
  await expect(page.getByRole('dialog', { name: 'Ещё' }).getByRole('link', { name: 'Пользователи' })).toHaveCount(0)
  await page.getByRole('dialog', { name: 'Ещё' }).getByRole('button', { name: 'Выйти' }).click()
  await expect(page.getByRole('heading', { name: 'Вход', exact: true })).toBeVisible()
  await expect(page.getByText('120,00 USD')).toHaveCount(0)
})

test('401 при чтении платежей возвращает ко входу и убирает приватный экран', async ({ page }) => {
  let authenticated = true
  await page.route('**/api/v1/auth/me', (route) => route.fulfill(authenticated
    ? { status: 200, contentType: 'application/json', body: JSON.stringify({ id: 2, login: 'anna', role: 'user', is_protected: false, telegram_linked: false, created_at: '2026-10-24T09:00:00+03:00', updated_at: '2026-10-24T09:00:00+03:00' }) }
    : { status: 401, contentType: 'application/json', body: JSON.stringify({ error: { code: 'unauthorized', message: 'Войдите снова' } }) }))
  await page.route('**/api/v1/config', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ timezone_offset: '+03:00', timezone_label: 'GMT+3', today: '2026-10-24', reminder_days_before: 3, currencies: ['RUB', 'USD', 'EUR'], periodicities: ['monthly'], telegram_bot_username: null, miniapp_url: null, channels: { telegram: true, email: false, webhook: false, extra: false }, dev_mode: false }) }))
  await page.route('**/api/v1/payment-occurrences?**', (route) => {
    authenticated = false
    return route.fulfill({ status: 401, contentType: 'application/json', body: JSON.stringify({ error: { code: 'unauthorized', message: 'Войдите снова' } }) })
  })
  await page.goto('/payments')
  await expect(page.getByRole('heading', { name: 'Вход', exact: true })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Платежи', exact: true })).toHaveCount(0)
})

test('список показывает следующую страницу, а ошибку не подменяет пустой выборкой', async ({ page }) => {
  const user = { id: 2, login: 'anna', role: 'user', is_protected: false, telegram_linked: false, created_at: '2026-10-24T09:00:00+03:00', updated_at: '2026-10-24T09:00:00+03:00' }
  const config = { timezone_offset: '+03:00', timezone_label: 'GMT+3', today: '2026-10-24', reminder_days_before: 3, currencies: ['RUB', 'USD', 'EUR'], periodicities: ['monthly'], telegram_bot_username: null, miniapp_url: null, channels: { telegram: true, email: false, webhook: false, extra: false }, dev_mode: false }
  await page.route('**/api/v1/auth/me', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(user) }))
  await page.route('**/api/v1/config', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(config) }))
  let fail = false
  await page.route('**/api/v1/payment-occurrences?**', (route) => {
    if (fail) return route.fulfill({ status: 500, contentType: 'application/json', body: JSON.stringify({ error: { code: 'internal_error', message: 'Ошибка сервера' } }) })
    const offset = Number(new URL(route.request().url()).searchParams.get('offset'))
    const items = Array.from({ length: offset === 0 ? 50 : 1 }, (_, index) => ({
      id: offset + index + 1, recurring_payment_id: 7, title: `Период ${offset + index + 1}`, amount: '10.00', currency: 'RUB', due_date: '2026-11-10', status: 'unpaid', paid_date: null, is_overdue: false, is_paid_late: false, state: 'upcoming', recurring_status: 'active', assign_all: false, assignees: [], paid_by: null, paid_via: null, reminder_sent_at: null, attachments_count: 0, version: 1, created_at: '2026-10-24T09:00:00+03:00', updated_at: '2026-10-24T09:00:00+03:00',
    }))
    return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ items, total: 51, limit: 50, offset }) })
  })
  await page.goto('/payments')
  await expect(page.getByRole('article')).toHaveCount(50)
  await page.getByRole('button', { name: 'Далее' }).click()
  await expect(page.getByRole('article')).toHaveCount(1)
  await expect(page.getByText('Страница 2 из 2')).toBeVisible()
  fail = true
  await page.reload()
  await expect(page.getByRole('heading', { name: 'Не удалось загрузить платежи' })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Платежей пока нет' })).toHaveCount(0)
})

test('администратор создаёт и прекращает регулярный платёж по контракту', async ({ page }) => {
  const user = { id: 1, login: 'admin', role: 'admin', is_protected: true, telegram_linked: false, created_at: '2026-10-24T09:00:00+03:00', updated_at: '2026-10-24T09:00:00+03:00' }
  const config = { timezone_offset: '+03:00', timezone_label: 'GMT+3', today: '2026-10-24', reminder_days_before: 3, currencies: ['RUB', 'USD', 'EUR'], periodicities: ['monthly'], telegram_bot_username: null, miniapp_url: null, channels: { telegram: true, email: false, webhook: false, extra: false }, dev_mode: false }
  let item: Record<string, unknown> | undefined
  await page.route('**/api/v1/auth/me', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(user) }))
  await page.route('**/api/v1/config', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(config) }))
  const anna = { id: 2, login: 'anna', role: 'user', is_protected: false, telegram_linked: true, created_at: '2026-10-24T09:00:00+03:00', updated_at: '2026-10-24T09:00:00+03:00' }
  await page.route('**/api/v1/users?**', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ items: [anna], total: 1, limit: 200, offset: 0 }) }))
  await page.route('**/api/v1/recurring-payments?**', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ items: item ? [item] : [], total: item ? 1 : 0, limit: 50, offset: 0 }) }))
  await page.route('**/api/v1/recurring-payments', (route) => {
    const body = route.request().postDataJSON()
    expect(body).toEqual({ title: 'Сервер', amount: '120.00', currency: 'USD', next_due_date: '2026-11-10', periodicity: 'monthly', assign_all: false, assignee_ids: [2] })
    item = { id: 7, title: body.title, amount: body.amount, currency: body.currency, periodicity: body.periodicity, next_due_date: body.next_due_date, anchor_day: 10, first_due_date: '2026-11-10', status: 'active', created_at: '2026-10-24T09:00:00+03:00', stopped_at: null, created_by: { id: 1, login: 'admin' }, assign_all: false, assignees: [{ id: 2, login: 'anna' }], version: 1 }
    return route.fulfill({ status: 201, contentType: 'application/json', body: JSON.stringify(item) })
  })
  await page.route('**/api/v1/recurring-payments/7', (route) => {
    item = { ...item, status: 'stopped', next_due_date: null, stopped_at: '2026-10-24T09:05:00+03:00', version: 2 }
    return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(item) })
  })
  await page.goto('/recurring-payments')
  await expect(page.getByRole('heading', { name: 'Регулярных платежей пока нет' })).toBeVisible()
  await page.getByRole('link', { name: 'Добавить платёж' }).click()
  await page.getByRole('button', { name: 'Добавить платёж' }).click()
  await expect(page.getByText('Введите название')).toBeVisible()
  await page.getByRole('textbox', { name: 'Название' }).fill('Сервер')
  await page.getByRole('textbox', { name: 'Сумма' }).fill('120.00')
  await page.getByRole('combobox', { name: 'Валюта *' }).click()
  await page.getByRole('option', { name: 'USD' }).click()
  await page.getByLabel('Ближайшая дата оплаты').fill('2026-11-10')
  await page.getByRole('checkbox', { name: 'anna' }).check()
  await page.getByRole('button', { name: 'Добавить платёж' }).click()
  await expect(page.getByRole('heading', { name: 'Регулярные платежи' })).toBeVisible()
  await expect(page.getByRole('article').getByText('120,00 USD')).toBeVisible()
  await expect(page.getByRole('article').getByText('anna', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Прекратить платёж' }).first().click()
  const dialog = page.getByRole('dialog', { name: 'Прекратить регулярный платёж?' })
  await expect(dialog.getByRole('button', { name: 'Оставить' })).toBeFocused()
  await expect(dialog.getByText('История сохранится.', { exact: false })).toBeVisible()
  await dialog.getByRole('button', { name: 'Прекратить платёж' }).click()
  await expect(dialog).toHaveCount(0)
  await expect(page.getByRole('article').getByText('Прекращён')).toBeVisible()
})

test('обычный пользователь не открывает административный маршрут', async ({ page }) => {
  await page.route('**/api/v1/auth/me', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ id: 2, login: 'anna', role: 'user', is_protected: false, telegram_linked: false, created_at: '2026-10-24T09:00:00+03:00', updated_at: '2026-10-24T09:00:00+03:00' }) }))
  await page.route('**/api/v1/config', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ timezone_offset: '+03:00', timezone_label: 'GMT+3', today: '2026-10-24', reminder_days_before: 3, currencies: ['RUB', 'USD', 'EUR'], periodicities: ['monthly'], telegram_bot_username: null, miniapp_url: null, channels: { telegram: true, email: false, webhook: false, extra: false }, dev_mode: false }) }))
  let adminRequests = 0
  await page.route('**/api/v1/recurring-payments?**', (route) => { adminRequests++; return route.abort() })
  await page.goto('/recurring-payments')
  await expect(page.getByRole('heading', { name: 'Нет доступа' })).toBeVisible()
  expect(adminRequests).toBe(0)
})

test('оплата, исправление даты и отмена меняют только выбранный период', async ({ page }) => {
  const user = { id: 2, login: 'anna', role: 'user', is_protected: false, telegram_linked: false, created_at: '2026-10-24T09:00:00+03:00', updated_at: '2026-10-24T09:00:00+03:00' }
  const config = { timezone_offset: '+03:00', timezone_label: 'GMT+3', today: '2026-11-15', reminder_days_before: 3, currencies: ['RUB', 'USD', 'EUR'], periodicities: ['monthly'], telegram_bot_username: null, miniapp_url: null, channels: { telegram: true, email: false, webhook: false, extra: false }, dev_mode: false }
  const base = { recurring_payment_id: 7, title: 'Сервер', amount: '120.00', currency: 'USD', status: 'unpaid', paid_date: null as string | null, is_overdue: true, is_paid_late: false, state: 'overdue', recurring_status: 'active', assign_all: false, assignees: [], paid_by: null, paid_via: null, reminder_sent_at: null, attachments_count: 0, version: 1, created_at: '2026-10-24T09:00:00+03:00', updated_at: '2026-10-24T09:00:00+03:00' }
  let current: Record<string, unknown> = { id: 42, due_date: '2026-11-10', ...base }
  const other = { id: 43, due_date: '2026-12-10', ...base, is_overdue: false, state: 'upcoming' }
  const bodies: unknown[] = []
  await page.route('**/api/v1/auth/me', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(user) }))
  await page.route('**/api/v1/config', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(config) }))
  await page.route('**/api/v1/payment-occurrences?**', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ items: [current, other], total: 2, limit: 50, offset: 0 }) }))
  await page.route('**/api/v1/payment-occurrences/42', (route) => {
    if (route.request().method() === 'GET') return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(current) })
    const body = route.request().postDataJSON()
    bodies.push(body)
    expect(body.expected_version).toBe(current.version)
    const paidDate = body.status === 'unpaid' ? null : body.paid_date
    const paid = body.status === 'paid' || (body.status === undefined && current.status === 'paid')
    current = { ...current, status: paid ? 'paid' : 'unpaid', paid_date: paidDate, is_overdue: !paid, is_paid_late: paid && paidDate > '2026-11-10', state: paid ? paidDate > '2026-11-10' ? 'paid_late' : 'paid' : 'overdue', version: Number(current.version) + 1 }
    return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(current) })
  })
  await page.goto('/payments/42')
  await page.getByRole('button', { name: 'Отметить оплату' }).click()
  await page.getByLabel('Фактическая дата оплаты').fill('2026-11-10')
  await page.getByRole('button', { name: 'Подтвердить оплату' }).click()
  await expect(page.getByText('Оплачено', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Изменить дату оплаты' }).click()
  await page.getByLabel('Фактическая дата оплаты').fill('2026-11-12')
  await page.getByRole('button', { name: 'Подтвердить оплату' }).click()
  await expect(page.getByText('Оплачено с опозданием')).toBeVisible()
  await page.getByRole('button', { name: 'Отменить отметку' }).click()
  await expect(page.getByRole('dialog', { name: 'Отменить отметку об оплате?' }).getByRole('button', { name: 'Оставить как есть' })).toBeFocused()
  await page.getByRole('dialog', { name: 'Отменить отметку об оплате?' }).getByRole('button', { name: 'Отменить отметку' }).click()
  await expect(page.getByText('Просрочено')).toBeVisible()
  expect(bodies).toEqual([
    { status: 'paid', paid_date: '2026-11-10', expected_version: 1 },
    { paid_date: '2026-11-12', expected_version: 2 },
    { status: 'unpaid', expected_version: 3 },
  ])
  await page.getByRole('link', { name: 'К списку платежей' }).click()
  await expect(page.getByRole('article')).toHaveCount(2)
  await expect(page.getByRole('article').filter({ hasText: '10.12.2026' }).getByText('Не оплачено')).toBeVisible()
})

test('конфликт версии перечитывает период без повторной записи', async ({ page }) => {
  await page.route('**/api/v1/auth/me', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ id: 2, login: 'anna', role: 'user', is_protected: false, telegram_linked: false, created_at: '2026-10-24T09:00:00+03:00', updated_at: '2026-10-24T09:00:00+03:00' }) }))
  await page.route('**/api/v1/config', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ timezone_offset: '+03:00', timezone_label: 'GMT+3', today: '2026-11-15', reminder_days_before: 3, currencies: ['RUB', 'USD', 'EUR'], periodicities: ['monthly'], telegram_bot_username: null, miniapp_url: null, channels: { telegram: true, email: false, webhook: false, extra: false }, dev_mode: false }) }))
  let item = { id: 42, recurring_payment_id: 7, title: 'Сервер', amount: '120.00', currency: 'USD', due_date: '2026-11-10', status: 'unpaid', paid_date: null as string | null, is_overdue: true, is_paid_late: false, state: 'overdue', recurring_status: 'active', assign_all: false, assignees: [], paid_by: null, paid_via: null, reminder_sent_at: null, attachments_count: 0, version: 1, created_at: '2026-10-24T09:00:00+03:00', updated_at: '2026-10-24T09:00:00+03:00' }
  let patchCount = 0
  await page.route('**/api/v1/payment-occurrences/42', (route) => {
    if (route.request().method() === 'GET') return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(item) })
    patchCount++
    item = { ...item, status: 'paid', paid_date: '2026-11-11', is_overdue: false, is_paid_late: true, state: 'paid_late', version: 2 }
    return route.fulfill({ status: 409, contentType: 'application/json', body: JSON.stringify({ error: { code: 'version_conflict', message: 'Запись изменена другим пользователем' } }) })
  })
  await page.goto('/payments/42')
  await page.getByRole('button', { name: 'Отметить оплату' }).click()
  await page.getByRole('button', { name: 'Подтвердить оплату' }).click()
  await expect(page.getByRole('alert').filter({ hasText: 'изменён другим пользователем' })).toBeVisible()
  await expect(page.getByText('Оплачено с опозданием')).toBeVisible()
  expect(patchCount).toBe(1)
})

test('сводка берёт диапазон и суммы с сервера и обновляется после оплаты', async ({ page }) => {
  await page.route('**/api/v1/auth/me', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ id: 2, login: 'anna', role: 'user', is_protected: false, telegram_linked: false, created_at: '2026-10-24T09:00:00+05:00', updated_at: '2026-10-24T09:00:00+05:00' }) }))
  await page.route('**/api/v1/config', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ timezone_offset: '+05:00', timezone_label: 'GMT+5', today: '2026-11-15', reminder_days_before: 4, currencies: ['RUB', 'USD', 'EUR'], periodicities: ['monthly'], telegram_bot_username: null, miniapp_url: null, channels: { telegram: true, email: false, webhook: false, extra: false }, dev_mode: false }) }))
  let item = { id: 42, recurring_payment_id: 7, title: 'Сервер', amount: '120.00', currency: 'USD', due_date: '2026-11-10', status: 'unpaid', paid_date: null as string | null, is_overdue: true, is_paid_late: false, state: 'overdue', recurring_status: 'active', assign_all: false, assignees: [], paid_by: null, paid_via: null, reminder_sent_at: null, attachments_count: 0, version: 1, created_at: '2026-10-24T09:00:00+05:00', updated_at: '2026-10-24T09:00:00+05:00' }
  let summaryReads = 0
  await page.route('**/api/v1/payments/summary?**', (route) => {
    summaryReads++
    const params = new URL(route.request().url()).searchParams
    const paid = item.status === 'paid'
    const zero = (currency: string) => ({ currency, total: '0.00', paid: '0.00', unpaid: '0.00', overdue: '0.00', count: 0 })
    return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ from: params.get('from'), to: params.get('to'), today: '2026-11-15', currencies: [zero('RUB'), { currency: 'USD', total: '120.00', paid: paid ? '120.00' : '0.00', unpaid: paid ? '0.00' : '120.00', overdue: paid ? '0.00' : '120.00', count: 1 }, zero('EUR')] }) })
  })
  await page.route('**/api/v1/payment-occurrences?**', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ items: [item], total: 1, limit: 50, offset: 0 }) }))
  await page.route('**/api/v1/payment-occurrences/42', (route) => {
    if (route.request().method() === 'GET') return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(item) })
    item = { ...item, status: 'paid', paid_date: '2026-11-10', is_overdue: false, state: 'paid', version: 2 }
    return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(item) })
  })
  await page.goto('/payments')
  const summary = page.locator('section[aria-label="Сводка"]')
  await summary.getByRole('button', { name: 'USD' }).click()
  await expect(summary.getByText('Не оплачено', { exact: true }).locator('..').getByText('120,00 USD')).toBeVisible()
  await expect(summary.getByText('01.11.2026 — 30.11.2026')).toBeVisible()
  await page.getByRole('link', { name: 'Открыть платёж' }).click()
  await page.getByRole('button', { name: 'Отметить оплату' }).click()
  await page.getByLabel('Фактическая дата оплаты').fill('2026-11-10')
  await page.getByRole('button', { name: 'Подтвердить оплату' }).click()
  await expect(page.getByText('Оплачено', { exact: true })).toBeVisible()
  await page.getByRole('link', { name: 'К списку платежей' }).click()
  await summary.getByRole('button', { name: 'USD' }).click()
  await expect(summary.getByText('Оплачено', { exact: true }).locator('..').getByText('120,00 USD')).toBeVisible()
  expect(summaryReads).toBeGreaterThanOrEqual(2)
})

test('администратор создаёт и удаляет обычного пользователя без пароля в списке', async ({ page }) => {
  const admin = { id: 1, login: 'admin', role: 'admin', is_protected: true, telegram_linked: false, created_at: '2026-10-24T09:00:00+03:00', updated_at: '2026-10-24T09:00:00+03:00' }
  let user: Record<string, unknown> | undefined
  await page.route('**/api/v1/auth/me', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(admin) }))
  await page.route('**/api/v1/config', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ timezone_offset: '+03:00', timezone_label: 'GMT+3', today: '2026-10-24', reminder_days_before: 3, currencies: ['RUB', 'USD', 'EUR'], periodicities: ['monthly'], telegram_bot_username: null, miniapp_url: null, channels: { telegram: true, email: false, webhook: false, extra: false }, dev_mode: false }) }))
  await page.route('**/api/v1/users?**', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ items: user ? [user] : [], total: user ? 1 : 0, limit: 50, offset: 0 }) }))
  await page.route('**/api/v1/users', (route) => {
    expect(route.request().postDataJSON()).toEqual({ login: 'anna', password: 'example-password' })
    user = { id: 2, login: 'anna', role: 'user', is_protected: false, telegram_linked: false, created_at: '2026-10-24T09:00:00+03:00', updated_at: '2026-10-24T09:00:00+03:00' }
    return route.fulfill({ status: 201, contentType: 'application/json', body: JSON.stringify(user) })
  })
  await page.route('**/api/v1/users/2', (route) => { user = undefined; return route.fulfill({ status: 204 }) })
  await page.goto('/users')
  await expect(page.getByRole('heading', { name: 'Пользователей пока нет' })).toBeVisible()
  await page.getByRole('link', { name: 'Добавить пользователя' }).click()
  await page.getByRole('textbox', { name: 'Логин' }).fill('anna')
  await page.getByLabel('Пароль').fill('example-password')
  await page.getByRole('button', { name: 'Добавить пользователя' }).click()
  await expect(page.getByRole('article').getByRole('heading', { name: 'anna' })).toBeVisible()
  await expect(page.getByText('example-password')).toHaveCount(0)
  await page.getByRole('button', { name: 'Удалить пользователя' }).first().click()
  const dialog = page.getByRole('dialog', { name: 'Удалить пользователя?' })
  await expect(dialog.getByRole('button', { name: 'Оставить' })).toBeFocused()
  await dialog.getByRole('button', { name: 'Удалить пользователя' }).click()
  await expect(page.getByRole('heading', { name: 'Пользователей пока нет' })).toBeVisible()
})

test('календарь различает реальный период и расчётный план', async ({ page }) => {
  await page.route('**/api/v1/auth/me', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ id: 2, login: 'anna', role: 'user', is_protected: false, telegram_linked: false, created_at: '2026-10-24T09:00:00+03:00', updated_at: '2026-10-24T09:00:00+03:00' }) }))
  await page.route('**/api/v1/config', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ timezone_offset: '+03:00', timezone_label: 'GMT+3', today: '2026-11-15', reminder_days_before: 3, currencies: ['RUB', 'USD', 'EUR'], periodicities: ['monthly'], telegram_bot_username: null, miniapp_url: null, channels: { telegram: true, email: false, webhook: false, extra: false }, dev_mode: false }) }))
  const totals = (currency: string, total: string) => ({ currency, total, paid: '0.00', unpaid: total, overdue: '0.00', count: total === '0.00' ? 0 : 1 })
  await page.route('**/api/v1/calendar?**', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ month: '2026-11', today: '2026-11-15', days: [
    { date: '2026-11-10', items: [{ occurrence_id: 42, recurring_payment_id: 7, title: 'Сервер', amount: '120.00', currency: 'USD', due_date: '2026-11-10', state: 'overdue', is_projected: false }], totals: [totals('RUB', '0.00'), totals('USD', '120.00'), totals('EUR', '0.00')] },
    { date: '2026-11-20', items: [{ occurrence_id: null, recurring_payment_id: 8, title: 'Подписка', amount: '20.00', currency: 'EUR', due_date: '2026-11-20', state: null, is_projected: true }], totals: [totals('RUB', '0.00'), totals('USD', '0.00'), totals('EUR', '20.00')] },
  ], month_totals: [totals('RUB', '0.00'), totals('USD', '120.00'), totals('EUR', '20.00')] }) }))
  await page.goto('/calendar?month=2026-11')
  await expect(page.getByRole('heading', { name: 'В этот день платежей нет' })).toBeVisible()
  await page.getByRole('button', { name: '10, платежей: 1' }).click()
  await expect(page.getByRole('link', { name: 'Открыть платёж' })).toHaveAttribute('href', '/payments/42')
  await expect(page.getByRole('region', { name: 'Итоги дня' }).getByText('Начислено: 120,00 USD')).toBeVisible()
  await page.getByRole('button', { name: '20, платежей: 1' }).click()
  await expect(page.getByText('План', { exact: true })).toBeVisible()
  await expect(page.getByRole('link', { name: 'Открыть платёж' })).toHaveCount(0)
  await expect(page).toHaveURL(/day=2026-11-20/)
})

test('бюджет показывает серверный план месяца и года по валютам', async ({ page }) => {
  await page.route('**/api/v1/auth/me', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ id: 2, login: 'anna', role: 'user', is_protected: false, telegram_linked: false, created_at: '2026-10-24T09:00:00+03:00', updated_at: '2026-10-24T09:00:00+03:00' }) }))
  await page.route('**/api/v1/config', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ timezone_offset: '+03:00', timezone_label: 'GMT+3', today: '2026-11-15', reminder_days_before: 3, currencies: ['RUB', 'USD', 'EUR'], periodicities: ['monthly'], telegram_bot_username: null, miniapp_url: null, channels: { telegram: true, email: false, webhook: false, extra: false }, dev_mode: false }) }))
  const requests: string[] = []
  await page.route('**/api/v1/budget?**', (route) => {
    const params = new URL(route.request().url()).searchParams
    requests.push(params.toString())
    const annual = params.get('period') === 'year'
    const zero = (currency: string) => ({ currency, planned: '0.00', existing_paid: '0.00', existing_unpaid: '0.00', projected: '0.00' })
    return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ period: annual ? 'year' : 'month', from: annual ? '2026-01-01' : '2026-11-01', to: annual ? '2026-12-31' : '2026-11-30', currencies: [{ currency: 'RUB', planned: annual ? '345.00' : '100.00', existing_paid: '20.00', existing_unpaid: '30.00', projected: annual ? '295.00' : '50.00' }, zero('USD'), zero('EUR')] }) })
  })
  await page.goto('/budget')
  await expect(page.getByRole('region', { name: 'План RUB' }).getByText('100,00 RUB')).toBeVisible()
  await page.getByRole('combobox', { name: 'Период' }).click()
  await page.getByRole('option', { name: 'Год' }).click()
  await page.getByRole('button', { name: 'Показать' }).click()
  await expect(page.getByRole('region', { name: 'План RUB' }).getByText('345,00 RUB')).toBeVisible()
  await expect(page.getByRole('region', { name: 'План USD' })).toBeVisible()
  await expect(page.getByRole('region', { name: 'План EUR' })).toBeVisible()
  expect(requests).toContain('period=month&year=2026&month=11')
  expect(requests).toContain('period=year&year=2026')
})

test('вложения конкретного периода добавляются, скачиваются и удаляются через API', async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 740 })
  const user = { id: 2, login: 'anna', role: 'user', is_protected: false, telegram_linked: false, created_at: '2026-10-24T09:00:00+03:00', updated_at: '2026-10-24T09:00:00+03:00' }
  const config = { timezone_offset: '+03:00', timezone_label: 'GMT+3', today: '2026-10-24', reminder_days_before: 3, currencies: ['RUB', 'USD', 'EUR'], periodicities: ['monthly'], telegram_bot_username: null, miniapp_url: null, channels: { telegram: true, email: false, webhook: false, extra: false }, dev_mode: false }
  const occurrence = { id: 42, recurring_payment_id: 7, title: 'Сервер', amount: '120.00', currency: 'USD', due_date: '2026-11-10', status: 'unpaid', paid_date: null, is_overdue: false, is_paid_late: false, state: 'upcoming', recurring_status: 'active', assign_all: false, assignees: [], paid_by: null, paid_via: null, reminder_sent_at: null, attachments_count: 0, version: 1, created_at: '2026-10-24T09:00:00+03:00', updated_at: '2026-10-24T09:00:00+03:00' }
  type TestAttachment = { id: number; occurrence_id: number; kind: string; url: string | null; title: string | null; file_name: string | null; content_type: string | null; size_bytes: number | null; created_at: string; created_by: typeof user }
  const attachments: TestAttachment[] = [{ id: 8, occurrence_id: 42, kind: 'file', url: '/api/v1/attachments/8/file', title: null, file_name: 'receipt.pdf', content_type: 'application/pdf', size_bytes: 4, created_at: '2026-10-24T09:00:00+03:00', created_by: user }]
  await page.route('**/api/v1/auth/me', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(user) }))
  await page.route('**/api/v1/config', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(config) }))
  await page.route('**/api/v1/payment-occurrences/42', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(occurrence) }))
  await page.route('**/api/v1/payment-occurrences/42/attachments', async (route) => {
    if (route.request().method() === 'POST') {
      const body = route.request().postDataJSON() as { url: string; title: string }
      const item = { id: 9, occurrence_id: 42, kind: 'link', url: body.url, title: body.title, file_name: null, content_type: null, size_bytes: null, created_at: '2026-10-24T09:00:00+03:00', created_by: user }
      attachments.push(item)
      return route.fulfill({ status: 201, contentType: 'application/json', body: JSON.stringify(item) })
    }
    return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(attachments) })
  })
  let fileDownloads = 0
  await page.route('**/api/v1/attachments/8/file', (route) => { fileDownloads++; return route.fulfill({ status: 200, contentType: 'application/pdf', body: '%PDF' }) })
  await page.route('**/api/v1/attachments/9', (route) => { attachments.pop(); return route.fulfill({ status: 204 }) })
  await page.goto('/payments/42')
  await expect(page.getByRole('heading', { name: 'Чеки и ссылки' })).toBeVisible()
  await page.getByRole('button', { name: 'Скачать' }).click()
  await expect.poll(() => fileDownloads).toBe(1)
  await page.getByRole('textbox', { name: 'Адрес ссылки' }).fill('javascript:alert(1)')
  await page.getByRole('button', { name: 'Добавить ссылку' }).click()
  await expect(page.getByText('Введите полный адрес http:// или https:// длиной до 2048 символов.')).toBeVisible()
  await page.getByRole('textbox', { name: 'Адрес ссылки' }).fill('https://example.org/receipt')
  await page.getByRole('button', { name: 'Добавить ссылку' }).click()
  await expect(page.getByText('Ссылка добавлена.')).toBeVisible()
  await expect(page.getByText('https://example.org/receipt')).toHaveCount(0)
  await page.reload()
  await expect(page.getByRole('button', { name: 'Открыть' })).toBeVisible()
  page.on('dialog', (dialog) => void dialog.accept())
  await page.getByRole('button', { name: 'Удалить' }).last().click()
  await expect(page.getByRole('button', { name: 'Открыть' })).toHaveCount(0)
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(320)
})

test('журнал доступен администратору и передаёт фильтры серверу', async ({ page }) => {
  const user = { id: 1, login: 'admin', role: 'admin', is_protected: true, telegram_linked: false, created_at: '2026-10-24T09:00:00+03:00', updated_at: '2026-10-24T09:00:00+03:00' }
  const config = { timezone_offset: '+03:00', timezone_label: 'GMT+3', today: '2026-10-24', reminder_days_before: 3, currencies: ['RUB', 'USD', 'EUR'], periodicities: ['monthly'], telegram_bot_username: null, miniapp_url: null, channels: { telegram: true, email: false, webhook: false, extra: false }, dev_mode: false }
  const requests: string[] = []
  await page.route('**/api/v1/auth/me', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(user) }))
  await page.route('**/api/v1/config', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(config) }))
  await page.route('**/api/v1/audit-log?**', (route) => {
    requests.push(new URL(route.request().url()).searchParams.toString())
    return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ items: [{ id: 5, at: '2026-10-24T09:00:00+03:00', actor: user, source: 'web', action: 'auth.login', object_type: 'user', object_id: 1, result: 'success', details: {}, ip: null }], total: 1, limit: 50, offset: 0 }) })
  })
  await page.goto('/audit-log')
  await expect(page.getByRole('heading', { name: 'Журнал действий' })).toBeVisible()
  await expect(page.getByText('auth.login')).toBeVisible()
  await page.getByRole('textbox', { name: 'Действие' }).fill('auth.')
  await page.getByRole('button', { name: 'Показать' }).click()
  await expect(page).toHaveURL(/action=auth\./)
  expect(requests).toContain('limit=50&offset=0&action=auth.')
})

test('администратор видит серверные статусы доставок по каналам', async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 740 })
  const user = { id: 1, login: 'admin', role: 'admin', is_protected: true, telegram_linked: false, created_at: '2026-10-24T09:00:00+03:00', updated_at: '2026-10-24T09:00:00+03:00' }
  const config = { timezone_offset: '+03:00', timezone_label: 'GMT+3', today: '2026-10-24', reminder_days_before: 3, currencies: ['RUB', 'USD', 'EUR'], periodicities: ['monthly'], telegram_bot_username: null, miniapp_url: null, channels: { telegram: true, email: true, webhook: true, extra: false }, dev_mode: false }
  const requests: string[] = []
  await page.route('**/api/v1/auth/me', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(user) }))
  await page.route('**/api/v1/config', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(config) }))
  await page.route('**/api/v1/notifications/deliveries?**', (route) => {
    requests.push(new URL(route.request().url()).searchParams.toString())
    return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ items: [{ id: 3, notification_type: 'payment.due_soon', occurrence_id: 42, channel: 'email', status: 'failed', attempts: 2, last_error: 'SMTP unavailable', sent_at: null, created_at: '2026-10-24T09:00:00+03:00' }], total: 1, limit: 50, offset: 0 }) })
  })
  await page.goto('/deliveries')
  await expect(page.getByRole('heading', { name: 'Доставки уведомлений' })).toBeVisible()
  await expect(page.getByText('Email · Ошибка')).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(320)
  await page.screenshot({ path: 'test-results/deliveries-admin-320.png', fullPage: true })
  await page.getByRole('combobox', { name: 'Канал' }).click()
  await page.getByRole('option', { name: 'Email' }).click()
  await page.getByRole('button', { name: 'Показать' }).click()
  await expect(page).toHaveURL(/channel=email/)
  expect(requests).toContain('limit=50&offset=0&channel=email')
})

test('диалог удерживает фокус и возвращает его после Escape', async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 740 })
  await page.goto('/_dev/ui')
  const trigger = page.getByRole('button', { name: 'Открыть диалог' })
  await trigger.click()
  const dialog = page.getByRole('dialog', { name: 'Пример диалога' })
  await expect(dialog).toBeVisible()
  await expect(page.getByRole('textbox', { name: 'Поле в диалоге' })).toBeFocused()
  await page.keyboard.press('Tab')
  expect(await page.evaluate(() => Boolean(document.activeElement?.closest('[role="dialog"]')))).toBe(true)
  await page.screenshot({ path: 'test-results/dialog-320.png', fullPage: true })
  await page.keyboard.press('Escape')
  await expect(dialog).toHaveCount(0)
  await expect(trigger).toBeFocused()
})

test('диалог помещается в низком viewport', async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 360 })
  await page.goto('/_dev/ui')
  await page.getByRole('button', { name: 'Открыть диалог' }).click()
  const bounds = await page.getByRole('dialog', { name: 'Пример диалога' }).boundingBox()
  expect(bounds).not.toBeNull()
  expect(bounds!.y).toBeGreaterThanOrEqual(0)
  expect(bounds!.y + bounds!.height).toBeLessThanOrEqual(360)
})

test('диалог остаётся внутри Telegram safe area при уменьшении viewport', async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 500 })
  await page.addInitScript(() => {
    const callbacks = new Map<string, () => void>()
    const app = {
      initData: 'только тестовый контекст',
      viewportHeight: 360,
      safeAreaInset: { top: 40, bottom: 50, left: 24, right: 12 },
      contentSafeAreaInset: { top: 0, bottom: 0, left: 0, right: 0 },
      isVersionAtLeast: () => true,
      ready: () => {}, expand: () => {},
      onEvent: (event: string, callback: () => void) => { callbacks.set(event, callback) },
      offEvent: (event: string) => { callbacks.delete(event) },
    }
    window.Telegram = { WebApp: app }
    ;(window as Window & { setTestViewport: (height: number) => void }).setTestViewport = (height) => {
      app.viewportHeight = height
      callbacks.get('viewportChanged')?.()
    }
  })
  await page.goto('/_dev/ui')
  await expect(page.locator('html')).toHaveCSS('--app-viewport-height', '360px')
  await page.getByRole('button', { name: 'Открыть диалог' }).click()
  const dialog = page.getByRole('dialog', { name: 'Пример диалога' })
  const bounds = await dialog.boundingBox()
  expect(bounds).not.toBeNull()
  expect(bounds!.y).toBeGreaterThanOrEqual(40)
  expect(bounds!.y + bounds!.height).toBeLessThanOrEqual(310)
  expect(bounds!.x).toBeGreaterThanOrEqual(40)
  expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(292)
  await page.evaluate(() => (window as Window & { setTestViewport: (height: number) => void }).setTestViewport(280))
  await expect(page.locator('html')).toHaveCSS('--app-viewport-height', '280px')
  const compactBounds = await dialog.boundingBox()
  expect(compactBounds).not.toBeNull()
  expect(compactBounds!.y).toBeGreaterThanOrEqual(40)
  expect(compactBounds!.y + compactBounds!.height).toBeLessThanOrEqual(230)
  await dialog.getByRole('button', { name: 'Закрыть' }).click()
  await expect(dialog).toHaveCount(0)
})

test('представления доступны при масштабе 200%', async ({ page }) => {
  await page.setViewportSize({ width: 640, height: 740 })
  await page.goto('/_dev/ui')
  await page.evaluate(() => { document.body.style.zoom = '2' })
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(640)
  await expect(page.getByRole('region', { name: 'Сводка' }).getByRole('button', { name: 'EUR' })).toBeVisible()
  await expect(page.getByRole('article').first()).toBeVisible()
  await page.screenshot({ path: 'test-results/dev-ui-200-percent.png', fullPage: true })
})

test('широкая оболочка не растягивается за пределы 1120 px', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  await page.goto('/_dev/ui')
  const bounds = await page.locator('main').boundingBox()
  expect(bounds).not.toBeNull()
  expect(bounds!.width).toBeLessThanOrEqual(1120)
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(1440)
})
