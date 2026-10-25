import { Link, useOutletContext, useParams } from 'react-router'
import type { SessionContext } from '@/app/SessionGate'
import { useGetRecurringPaymentQuery } from '@/entities/recurring-payment'
import { EditRecurringPaymentForm } from '@/features/edit-recurring-payment'
import { useGetUsersQuery } from '@/features/manage-user'
import { getHttpStatus } from '@/shared/api'
import { ErrorState, LoadingState } from '@/shared/ui'
import styles from './EditRecurringPaymentPage.module.css'

export function EditRecurringPaymentPage() {
  const { config } = useOutletContext<SessionContext>()
  const id = Number(useParams().id)
  const valid = Number.isSafeInteger(id) && id > 0
  const { data: payment, error, isLoading, refetch } = useGetRecurringPaymentQuery(id, { skip: !valid, refetchOnMountOrArgChange: true })
  const users = useGetUsersQuery({ limit: 200, offset: 0 })
  return <main className={styles.page}>
    <Link to="/recurring-payments">К регулярным платежам</Link>
    <h1>Изменить платёж</h1>
    <p>Даты — {config.timezone_label}</p>
    {!valid && <ErrorState title="Платёж не найден" />}
    {valid && isLoading && <LoadingState />}
    {valid && error && <ErrorState title={getHttpStatus(error) === 404 ? 'Платёж не найден' : 'Не удалось загрузить платёж'} onRetry={getHttpStatus(error) === 404 ? undefined : () => void refetch()} />}
    {payment && payment.status !== 'active' && <ErrorState title="Прекращённый или завершённый платёж нельзя изменить" />}
    {payment && payment.status === 'active' && <EditRecurringPaymentForm
      key={payment.version}
      payment={payment}
      today={config.today}
      users={users.data?.items ?? []}
      usersLoading={users.isLoading}
      usersError={users.error ? 'Не удалось загрузить пользователей.' : undefined}
    />}
  </main>
}
