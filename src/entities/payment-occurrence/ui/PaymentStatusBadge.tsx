import styles from './PaymentStatusBadge.module.css'

export type PaymentDisplayStatus = 'unpaid' | 'overdue' | 'paid' | 'paid-late'

const labels: Record<PaymentDisplayStatus, string> = {
  unpaid: 'Не оплачено',
  overdue: 'Просрочено',
  paid: 'Оплачено',
  'paid-late': 'Оплачено с опозданием',
}

export function PaymentStatusBadge({ status }: { status: PaymentDisplayStatus }) {
  return <span className={`${styles.badge} ${styles[status]}`}>{labels[status]}</span>
}
