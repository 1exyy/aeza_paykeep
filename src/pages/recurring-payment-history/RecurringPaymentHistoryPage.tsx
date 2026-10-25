import { useState } from 'react'
import { Link, useParams } from 'react-router'
import { auditActionLabel, useGetAuditEventsQuery } from '@/entities/audit-event'
import { PaymentStatusBadge, toPaymentDisplayStatus, useGetOccurrencesQuery } from '@/entities/payment-occurrence'
import { assigneesLabel, periodicityLabel, statusLabel, useGetRecurringPaymentQuery } from '@/entities/recurring-payment'
import { getHttpStatus } from '@/shared/api'
import { formatDateOnly } from '@/shared/lib/date'
import { Button, EmptyState, ErrorState, LoadingState, MoneyValue } from '@/shared/ui'
import styles from './RecurringPaymentHistoryPage.module.css'

const STEP = 20
const via = { web: 'в приложении', telegram: 'в Telegram' } as const

/** Admin: periods of one recurring payment and what was done with it. */
export function RecurringPaymentHistoryPage() {
  const id = Number(useParams().id)
  const valid = Number.isSafeInteger(id) && id > 0
  const [periodsLimit, setPeriodsLimit] = useState(STEP)
  const [eventsLimit, setEventsLimit] = useState(STEP)
  const payment = useGetRecurringPaymentQuery(id, { skip: !valid })
  const periods = useGetOccurrencesQuery({ limit: periodsLimit, offset: 0, recurring_payment_id: id, sort: '-due_date' }, { skip: !valid })
  const events = useGetAuditEventsQuery({ limit: eventsLimit, offset: 0, recurring_payment_id: id }, { skip: !valid })

  if (!valid) return <main className={styles.page}><Link to="/recurring-payments">К регулярным платежам</Link><ErrorState title="Платёж не найден" /></main>
  const item = payment.data
  return <main className={styles.page}>
    <Link to="/recurring-payments">К регулярным платежам</Link>
    {payment.isLoading && <LoadingState />}
    {payment.error && <ErrorState title={getHttpStatus(payment.error) === 404 ? 'Платёж не найден' : 'Не удалось загрузить платёж'} onRetry={getHttpStatus(payment.error) === 404 ? undefined : () => void payment.refetch()} />}
    {item && <>
      <h1>История: {item.title}</h1>
      <p className={styles.meta}><MoneyValue value={item.amount} currency={item.currency} /> · {periodicityLabel(item)} · {statusLabel(item)}</p>
      <p className={styles.meta}>Ответственные: {assigneesLabel(item)}</p>
    </>}

    <h2>Периоды</h2>
    {!periods.currentData && periods.isFetching && <LoadingState />}
    {!periods.currentData && periods.error && <ErrorState title="Не удалось загрузить периоды" onRetry={() => void periods.refetch()} />}
    {periods.currentData && (periods.currentData.total === 0
      ? <EmptyState title="Периодов нет" description="У платежа нет сохранённых периодов." />
      : <>
        <ol className={styles.list}>
          {periods.currentData.items.map((period) => <li key={period.id} className={styles.card}>
            <div className={styles.row}>
              <Link to={`/payments/${period.id}`}>Срок {formatDateOnly(period.due_date)}</Link>
              <PaymentStatusBadge status={toPaymentDisplayStatus(period.state)} />
            </div>
            <span><MoneyValue value={period.amount} currency={period.currency} /></span>
            {period.paid_date && <span>Оплачено {formatDateOnly(period.paid_date)}{period.paid_by ? ` — ${period.paid_by.login}` : ''}{period.paid_via ? `, ${via[period.paid_via]}` : ''}</span>}
          </li>)}
        </ol>
        {periods.currentData.total > periods.currentData.items.length && <div className={styles.more}><Button variant="secondary" pending={periods.isFetching} onClick={() => setPeriodsLimit(periodsLimit + STEP)}>Показать ещё</Button></div>}
      </>)}

    <h2>Действия</h2>
    {!events.currentData && events.isFetching && <LoadingState />}
    {!events.currentData && events.error && <ErrorState title="Не удалось загрузить журнал" onRetry={() => void events.refetch()} />}
    {events.currentData && (events.currentData.total === 0
      ? <EmptyState title="Записей нет" description="По этому платежу ещё ничего не делали." />
      : <>
        <ol className={styles.list}>
          {events.currentData.items.map((event) => <li key={event.id} className={styles.card}>
            <strong>{auditActionLabel(event.action)}{event.result === 'failure' ? ' — отказ' : ''}</strong>
            <span>{event.at.slice(0, 16).replace('T', ' ')} · {event.actor?.login ?? 'Система'}{event.source === 'telegram' ? ' · Telegram' : ''}</span>
          </li>)}
        </ol>
        {events.currentData.total > events.currentData.items.length && <div className={styles.more}><Button variant="secondary" pending={events.isFetching} onClick={() => setEventsLimit(eventsLimit + STEP)}>Показать ещё</Button></div>}
      </>)}
  </main>
}
