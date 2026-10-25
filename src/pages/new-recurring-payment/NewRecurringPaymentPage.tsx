import { Link, useOutletContext } from 'react-router'
import type { SessionContext } from '@/app/SessionGate'
import { CreateRecurringPaymentForm } from '@/features/create-recurring-payment'
import { useGetUsersQuery } from '@/features/manage-user'
import styles from './NewRecurringPaymentPage.module.css'

export function NewRecurringPaymentPage() {
  const { config } = useOutletContext<SessionContext>()
  const { data: users, isLoading, error } = useGetUsersQuery({ limit: 200, offset: 0 })
  return <main className={styles.page}>
    <Link to="/recurring-payments">К регулярным платежам</Link>
    <h1>Новый регулярный платёж</h1>
    <p>Даты — {config.timezone_label}</p>
    <CreateRecurringPaymentForm
      today={config.today}
      users={users?.items ?? []}
      usersLoading={isLoading}
      usersError={error ? 'Не удалось загрузить пользователей. Платёж можно создать без ответственных.' : undefined}
    />
  </main>
}
