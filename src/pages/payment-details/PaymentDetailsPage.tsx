import { useEffect } from 'react'
import { Link, useNavigate, useOutletContext, useParams } from 'react-router'
import type { SessionContext } from '@/app/SessionGate'
import { PaymentStatusBadge, toPaymentDisplayStatus, useGetOccurrenceQuery } from '@/entities/payment-occurrence'
import { assigneesLabel } from '@/entities/recurring-payment'
import { PaymentActions } from '@/features/set-payment-status'
import { AttachmentsPanel } from '@/features/manage-attachments'
import { getHttpStatus } from '@/shared/api'
import { formatDateOnly } from '@/shared/lib/date'
import { bindTelegramBackButton } from '@/shared/lib/telegram'
import { MoneyValue, ErrorState, LoadingState } from '@/shared/ui'
import styles from './PaymentDetailsPage.module.css'

function dayWord(count: number): string {
  if (count % 100 >= 11 && count % 100 <= 14) return 'дней'
  return count % 10 === 1 ? 'день' : count % 10 >= 2 && count % 10 <= 4 ? 'дня' : 'дней'
}

export function PaymentDetailsPage() {
  const navigate = useNavigate()
  const { config } = useOutletContext<SessionContext>()
  const { id: rawId } = useParams()
  const id = Number(rawId)
  const validId = Number.isSafeInteger(id) && id > 0
  const { currentData: item, error, isFetching, refetch } = useGetOccurrenceQuery(id, { skip: !validId })

  useEffect(() => bindTelegramBackButton(() => navigate('/payments')), [navigate])

  return <main className={styles.page}>
    <Link className={styles.back} to="/payments">К списку платежей</Link>
    {!validId && <ErrorState title="Платёж не найден" />}
    {validId && !item && isFetching && <LoadingState />}
    {validId && !item && error && <ErrorState title={getHttpStatus(error) === 404 ? 'Платёж не найден' : getHttpStatus(error) === 403 ? 'Нет доступа' : 'Не удалось загрузить платёж'} onRetry={getHttpStatus(error) === 404 || getHttpStatus(error) === 403 ? undefined : () => void refetch()} />}
    {item && <article>
      <h1>{item.title}</h1>
      <p className={styles.zone}>Даты — {config.timezone_label} (UTC{config.timezone_offset}). Настройка напоминаний: за {config.reminder_days_before} {dayWord(config.reminder_days_before)} до срока.</p>
      <p className={styles.amount}><MoneyValue value={item.amount} currency={item.currency} /></p>
      <PaymentStatusBadge status={toPaymentDisplayStatus(item.state)} />
      {isFetching && <p role="status">Обновляем платёж…</p>}
      {error && <p className={styles.warning} role="alert">Не удалось обновить данные. Показан последний подтверждённый платёж.</p>}
      <dl className={styles.dates}>
        <div><dt>Срок оплаты</dt><dd>{formatDateOnly(item.due_date)}</dd></div>
        <div><dt>Дата оплаты</dt><dd>{item.paid_date ? formatDateOnly(item.paid_date) : '—'}</dd></div>
        <div><dt>Ответственные</dt><dd>{assigneesLabel(item)}</dd></div>
      </dl>
      <PaymentActions item={item} today={config.today} disabled={isFetching || Boolean(error)} onUncertain={() => void refetch()} />
      <AttachmentsPanel occurrenceId={item.id} />
    </article>}
  </main>
}
