import { Link } from 'react-router'
import { formatDateOnly } from '@/shared/lib/date'
import type { Currency } from '@/shared/lib/money'
import { MoneyValue } from '@/shared/ui'
import { PaymentStatusBadge, type PaymentDisplayStatus } from './PaymentStatusBadge'
import styles from './PaymentCard.module.css'

type Props = {
  title: string
  amount: string
  currency: Currency
  dueDate: string
  paidDate?: string | null
  status: PaymentDisplayStatus
  detailsHref?: string
}

export function PaymentCard({ title, amount, currency, dueDate, paidDate, status, detailsHref }: Props) {
  const datePaidText = paidDate
    ? formatDateOnly(paidDate)
    : status === 'paid' || status === 'paid-late' ? 'Нет данных' : '—'

  return <article className={styles.card}>
    <div className={styles.header}>
      <h3 className={styles.title}>{title}</h3>
      <p className={styles.amount}><MoneyValue value={amount} currency={currency} /></p>
    </div>
    <dl className={styles.details}>
      <div><dt>Срок оплаты</dt><dd>{formatDateOnly(dueDate)}</dd></div>
      <div><dt>Статус</dt><dd><PaymentStatusBadge status={status} /></dd></div>
      <div><dt>Дата оплаты</dt><dd>{datePaidText}</dd></div>
    </dl>
    {detailsHref && <Link className={styles.link} to={detailsHref}>Открыть платёж</Link>}
  </article>
}
