import { Link, useOutletContext, useSearchParams } from 'react-router'
import { toPaymentDisplayStatus, useGetCalendarQuery, type CalendarItem, type CurrencyTotals } from '@/entities/payment-occurrence'
import type { SessionContext } from '@/app/SessionGate'
import { formatDateOnly } from '@/shared/lib/date'
import { formatMoney } from '@/shared/lib/money'
import { Button, EmptyState, ErrorState, LoadingState, MoneyValue } from '@/shared/ui'
import { ExportCalendar } from '@/features/export-calendar'
import styles from './CalendarPage.module.css'

const weekdays = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс']
const currencies = ['RUB', 'USD', 'EUR'] as const

function shiftMonth(month: string, delta: number): string {
  const [year, value] = month.split('-').map(Number)
  const date = new Date(Date.UTC(year!, value! - 1 + delta, 1))
  return `${date.getUTCFullYear()}-${String(date.getUTCMonth() + 1).padStart(2, '0')}`
}

function Totals({ values, label }: { values: CurrencyTotals[]; label: string }) {
  if (values.length !== 3 || new Set(values.map(({ currency }) => currency)).size !== 3) return <ErrorState title={`Не удалось отобразить ${label.toLowerCase()}`} />
  return <section className={styles.totals} aria-label={label}>
    <h3>{label}</h3>
    {currencies.map((currency) => {
      const entry = values.find((value) => value.currency === currency)
      if (!entry) return null
      return <div key={currency}><strong>{currency}</strong><span>Начислено: {formatMoney(entry.total, currency)}</span><span>Оплачено: {formatMoney(entry.paid, currency)}</span><span>Не оплачено: {formatMoney(entry.unpaid, currency)}</span><span>Просрочено: {formatMoney(entry.overdue, currency)}</span></div>
    })}
  </section>
}

function CalendarPayment({ item }: { item: CalendarItem }) {
  const state = item.is_projected ? 'План' : item.state ? ({ unpaid: 'Не оплачено', overdue: 'Просрочено', paid: 'Оплачено', 'paid-late': 'Оплачено с опозданием' }[toPaymentDisplayStatus(item.state)]) : 'Состояние недоступно'
  return <li className={styles.payment}>
    <strong>{item.title}</strong>
    <MoneyValue value={item.amount} currency={item.currency} />
    <span>{state}</span>
    {!item.is_projected && item.occurrence_id !== null && <Link to={`/payments/${item.occurrence_id}`}>Открыть платёж</Link>}
  </li>
}

export function CalendarPage() {
  const { config } = useOutletContext<SessionContext>()
  const [params, setParams] = useSearchParams()
  const monthParam = params.get('month')
  const month = monthParam && /^\d{4}-(0[1-9]|1[0-2])$/.test(monthParam) ? monthParam : config.today.slice(0, 7)
  const [year, value] = month.split('-').map(Number)
  const monthDate = new Date(Date.UTC(year!, value! - 1, 1))
  const lastDay = new Date(Date.UTC(year!, value!, 0)).getUTCDate()
  const firstWeekday = (monthDate.getUTCDay() + 6) % 7
  const dayParam = params.get('day')
  const defaultDay = config.today.startsWith(`${month}-`) ? config.today : `${month}-01`
  const selectedDay = dayParam?.startsWith(`${month}-`) && Number(dayParam.slice(-2)) >= 1 && Number(dayParam.slice(-2)) <= lastDay ? dayParam : defaultDay
  const { currentData, error, isFetching, refetch } = useGetCalendarQuery(month)
  const chosen = currentData?.days.find((day) => day.date === selectedDay)
  const counts = new Map(currentData?.days.map((day) => [day.date, day.items.length]) ?? [])
  const setMonth = (nextMonth: string) => setParams({ month: nextMonth })
  const setDay = (day: string) => setParams({ month, day })

  return <main className={styles.page}>
    <h1>Календарь оплат</h1>
    <p className={styles.zone}>Даты — {config.timezone_label}</p>
    <ExportCalendar month={month} />
    <div className={styles.monthNav}>
      <Button variant="secondary" onClick={() => setMonth(shiftMonth(month, -1))} aria-label="Предыдущий месяц">‹</Button>
      <h2>{new Intl.DateTimeFormat('ru-RU', { month: 'long', year: 'numeric', timeZone: 'UTC' }).format(monthDate)}</h2>
      <Button variant="secondary" onClick={() => setMonth(shiftMonth(month, 1))} aria-label="Следующий месяц">›</Button>
    </div>
    {!currentData && isFetching && <LoadingState />}
    {!currentData && error && <ErrorState title="Не удалось загрузить календарь" onRetry={() => void refetch()} />}
    {currentData && <>
      {isFetching && <p role="status">Обновляем календарь…</p>}
      {error && <p className={styles.warning} role="alert">Не удалось обновить календарь. Показаны последние подтверждённые данные. <Button variant="secondary" onClick={() => void refetch()}>Повторить</Button></p>}
      <div className={styles.grid} role="group" aria-label="Дни месяца">
        {weekdays.map((day) => <strong key={day}>{day}</strong>)}
        {Array.from({ length: firstWeekday }, (_, index) => <span key={`blank-${index}`} aria-hidden="true" />)}
        {Array.from({ length: lastDay }, (_, index) => {
          const day = `${month}-${String(index + 1).padStart(2, '0')}`
          const count = counts.get(day) ?? 0
          return <button key={day} type="button" className={day === selectedDay ? styles.selectedDay : styles.day} aria-pressed={day === selectedDay} aria-label={`${index + 1}, платежей: ${count}`} onClick={() => setDay(day)}>{index + 1}{count > 0 && <span className={styles.marker} aria-hidden="true" />}</button>
        })}
      </div>
      <section className={styles.selected}>
        <h2>{formatDateOnly(selectedDay)}</h2>
        {chosen ? <><Totals values={chosen.totals} label="Итоги дня" /><ul className={styles.payments}>{chosen.items.map((item, index) => <CalendarPayment key={`${item.occurrence_id ?? 'plan'}-${item.recurring_payment_id}-${index}`} item={item} />)}</ul></> : <EmptyState title="В этот день платежей нет" description="Выберите другую дату или месяц." />}
      </section>
      <Totals values={currentData.month_totals} label="Итоги месяца" />
    </>}
  </main>
}
