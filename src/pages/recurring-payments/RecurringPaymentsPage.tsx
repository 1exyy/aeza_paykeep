import { Link, useSearchParams } from 'react-router'
import { assigneesLabel, periodicityLabel, statusLabel, useGetRecurringPaymentsQuery } from '@/entities/recurring-payment'
import { StopRecurringPayment } from '@/features/stop-recurring-payment'
import { getHttpStatus } from '@/shared/api'
import { formatDateOnly } from '@/shared/lib/date'
import { Button, EmptyState, ErrorState, LoadingState, MoneyValue } from '@/shared/ui'
import styles from './RecurringPaymentsPage.module.css'

const PAGE_SIZE = 50

export function RecurringPaymentsPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const rawPage = Number(searchParams.get('page'))
  const page = Number.isSafeInteger(rawPage) && rawPage > 0 ? rawPage : 1
  const { currentData, error, isFetching, refetch } = useGetRecurringPaymentsQuery({ limit: PAGE_SIZE, offset: (page - 1) * PAGE_SIZE })
  const setPage = (next: number) => setSearchParams(next === 1 ? {} : { page: String(next) })

  return <main className={styles.page}>
    <Link to="/payments">К платежам</Link>
    <div className={styles.heading}><h1>Регулярные платежи</h1><Link className={styles.newLink} to="/recurring-payments/new">Добавить платёж</Link></div>
    {!currentData && isFetching && <LoadingState />}
    {!currentData && error && <ErrorState title={getHttpStatus(error) === 403 ? 'Нет доступа' : 'Не удалось загрузить регулярные платежи'} onRetry={getHttpStatus(error) === 403 ? undefined : () => void refetch()} />}
    {currentData && <>
      {isFetching && <p role="status">Обновляем список…</p>}
      {error && <p className={styles.warning} role="alert">Не удалось обновить данные. Показана последняя подтверждённая выборка. <Button variant="secondary" onClick={() => void refetch()}>Повторить</Button></p>}
      {currentData.total === 0 ? <EmptyState title="Регулярных платежей пока нет" description="Добавьте первый регулярный платёж." /> : <div className={styles.list}>
        {currentData.items.map((item) => <article key={item.id} className={styles.card}>
          <div className={styles.cardHeading}><h2>{item.title}</h2><strong><MoneyValue value={item.amount} currency={item.currency} /></strong></div>
          <dl>
            <div><dt>Статус</dt><dd>{statusLabel(item)}</dd></div>
            <div><dt>Первый срок оплаты</dt><dd>{formatDateOnly(item.first_due_date)}</dd></div>
            <div><dt>Ближайший срок оплаты</dt><dd>{item.next_due_date ? formatDateOnly(item.next_due_date) : '—'}</dd></div>
            <div><dt>Периодичность</dt><dd>{periodicityLabel(item)}</dd></div>
            <div><dt>Ответственные</dt><dd>{assigneesLabel(item)}</dd></div>
          </dl>
          <div className={styles.actions}>
            <Link className={styles.editLink} to={`/recurring-payments/${item.id}/history`}>История</Link>
            {item.status === 'active' && <>
              <Link className={styles.editLink} to={`/recurring-payments/${item.id}/edit`}>Изменить</Link>
              <StopRecurringPayment id={item.id} title={item.title} onUncertain={() => void refetch()} />
            </>}
          </div>
        </article>)}
      </div>}
      {currentData.total > PAGE_SIZE && <nav className={styles.pagination} aria-label="Страницы регулярных платежей">
        <Button variant="secondary" disabled={page <= 1 || isFetching} onClick={() => setPage(page - 1)}>Назад</Button>
        <span>Страница {page} из {Math.ceil(currentData.total / PAGE_SIZE)}</span>
        <Button variant="secondary" disabled={page >= Math.ceil(currentData.total / PAGE_SIZE) || isFetching} onClick={() => setPage(page + 1)}>Далее</Button>
      </nav>}
    </>}
  </main>
}
