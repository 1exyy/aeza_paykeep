import { useState } from 'react'
import { ApplicationCard, useGetApplicationsQuery } from '@/features/review-applications'
import type { ApplicationStatus } from '@/features/review-applications'
import { Button, EmptyState, ErrorState, LoadingState } from '@/shared/ui'
import styles from './ApplicationsPage.module.css'

const PAGE_SIZE = 20
const tabs: { value: ApplicationStatus; label: string; empty: string }[] = [
  { value: 'pending', label: 'Новые', empty: 'Новых заявок нет' },
  { value: 'approved', label: 'Принятые', empty: 'Принятых заявок нет' },
  { value: 'rejected', label: 'Отклонённые', empty: 'Отклонённых заявок нет' },
]

/** The supervisor's only tab: team applications. */
export function ApplicationsPage() {
  const [status, setStatus] = useState<ApplicationStatus>('pending')
  const [page, setPage] = useState(1)
  const { currentData, error, isFetching, refetch } = useGetApplicationsQuery({ status, limit: PAGE_SIZE, offset: (page - 1) * PAGE_SIZE }, { refetchOnMountOrArgChange: true })
  const tab = tabs.find(({ value }) => value === status)!

  return <main className={styles.page}>
    <h1>Заявки на команды</h1>
    <div className={styles.tabs} role="group" aria-label="Статус заявок">
      {tabs.map(({ value, label }) => <button key={value} type="button" className={status === value ? styles.selected : styles.tab} aria-pressed={status === value} onClick={() => { setStatus(value); setPage(1) }}>{label}</button>)}
      <Button variant="secondary" pending={isFetching} onClick={() => void refetch()}>Обновить</Button>
    </div>
    {!currentData && isFetching && <LoadingState />}
    {!currentData && error && <ErrorState title="Не удалось загрузить заявки" onRetry={() => void refetch()} />}
    {currentData && (currentData.total === 0
      ? <EmptyState title={tab.empty} description="Заявки приходят из бота заявок." />
      : <div className={styles.list}>{currentData.items.map((item) => <ApplicationCard key={`${item.id}-${item.status}`} item={item} />)}</div>)}
    {currentData && currentData.total > PAGE_SIZE && <nav className={styles.pagination} aria-label="Страницы заявок">
      <Button variant="secondary" disabled={page <= 1 || isFetching} onClick={() => setPage(page - 1)}>Назад</Button>
      <span>Страница {page} из {Math.ceil(currentData.total / PAGE_SIZE)}</span>
      <Button variant="secondary" disabled={page >= Math.ceil(currentData.total / PAGE_SIZE) || isFetching} onClick={() => setPage(page + 1)}>Далее</Button>
    </nav>}
  </main>
}
