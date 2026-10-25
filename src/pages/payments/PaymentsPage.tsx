import { useOutletContext, useSearchParams } from 'react-router'
import { PaymentCard, toPaymentDisplayStatus, useGetOccurrencesQuery } from '@/entities/payment-occurrence'
import type { SessionContext } from '@/app/SessionGate'
import { useGetUsersQuery } from '@/features/manage-user'
import { getHttpStatus } from '@/shared/api'
import { formatDateOnly, isDateOnly } from '@/shared/lib/date'
import { Button, EmptyState, ErrorState, LoadingState, Select } from '@/shared/ui'
import { SummaryWidget } from '@/widgets/summary'
import { isStatusFilter, resolveAssignee, statusOptions, statusQuery } from './model/filters'
import styles from './PaymentsPage.module.css'

const PAGE_SIZE = 50

export function PaymentsPage() {
  const { config, user } = useOutletContext<SessionContext>()
  const [searchParams, setSearchParams] = useSearchParams()
  const rawPage = Number(searchParams.get('page'))
  const page = Number.isSafeInteger(rawPage) && rawPage > 0 ? rawPage : 1
  const rawStatus = searchParams.get('status')
  const status = isStatusFilter(rawStatus) ? rawStatus : 'all'
  const assignee = resolveAssignee(searchParams.get('assignee'), user.role)
  const dueFrom = searchParams.get('due_from')
  const dueTo = searchParams.get('due_to')
  const period = dueFrom && dueTo && isDateOnly(dueFrom) && isDateOnly(dueTo) && dueFrom <= dueTo ? { from: dueFrom, to: dueTo } : undefined
  const users = useGetUsersQuery({ limit: 200, offset: 0 }, { skip: user.role !== 'admin' })

  const { currentData, error, isFetching, refetch } = useGetOccurrencesQuery({
    limit: PAGE_SIZE,
    offset: (page - 1) * PAGE_SIZE,
    ...statusQuery(status),
    ...(assignee === 'me' ? { assignee_id: user.id } : assignee === 'all' ? {} : { assignee_id: assignee }),
    ...(period ? { due_from: period.from, due_to: period.to, sort: 'due_date' as const } : {}),
  })

  const update = (changes: Record<string, string | null>) => {
    const next = new URLSearchParams(searchParams)
    for (const [key, value] of Object.entries(changes)) {
      if (value === null) next.delete(key)
      else next.set(key, value)
    }
    next.delete('page')
    setSearchParams(next)
  }
  const setPage = (nextPage: number) => {
    const next = new URLSearchParams(searchParams)
    if (nextPage === 1) next.delete('page')
    else next.set('page', String(nextPage))
    setSearchParams(next)
  }

  const assigneeOptions = [
    { value: 'all', label: 'Все ответственные' },
    ...(user.role === 'admin'
      ? (users.data?.items ?? []).map(({ id, login }) => ({ value: String(id), label: login }))
      : [{ value: 'me', label: 'Мои платежи' }]),
  ]
  const filtered = status !== 'all' || assignee !== (user.role === 'admin' ? 'all' : 'me')

  return <main className={styles.page}>
    <h1>Платежи</h1>
    <p className={styles.context}>Сегодня: {formatDateOnly(config.today)} · Даты — {config.timezone_label}</p>
    <SummaryWidget today={config.today} timezoneLabel={config.timezone_label} onDetails={(range) => {
      update({ due_from: range.from, due_to: range.to })
      requestAnimationFrame(() => document.getElementById('payments-list')?.scrollIntoView({ behavior: 'smooth', block: 'start' }))
    }} />
    <div className={styles.listHeading}>
      <h2 id="payments-list">{period ? `Платежи за ${formatDateOnly(period.from)} — ${formatDateOnly(period.to)}` : 'Платежи за все периоды'}</h2>
      {period && <Button variant="secondary" onClick={() => update({ due_from: null, due_to: null })}>Все периоды</Button>}
    </div>
    <div className={styles.filters} role="group" aria-label="Фильтры платежей">
      <Select label="Статус" value={status} onValueChange={(value) => update({ status: value === 'all' ? null : value })} options={statusOptions} />
      <Select
        label="Ответственный"
        value={typeof assignee === 'number' ? String(assignee) : assignee}
        onValueChange={(value) => update({ assignee: value === (user.role === 'admin' ? 'all' : 'me') ? null : value })}
        options={assigneeOptions}
      />
    </div>
    {!currentData && isFetching && <LoadingState />}
    {!currentData && error && <ErrorState title={getHttpStatus(error) === 403 ? 'Нет доступа' : 'Не удалось загрузить платежи'} onRetry={() => void refetch()} />}
    {currentData && <>
      {isFetching && <p role="status">Обновляем список…</p>}
      {error && <p className={styles.warning} role="alert">Не удалось обновить данные. Показана последняя подтверждённая выборка. <Button variant="secondary" onClick={() => void refetch()}>Повторить</Button></p>}
      {currentData.items.length === 0 && currentData.total === 0
        ? (filtered || period
          ? <EmptyState title="Ничего не найдено" description="Измените фильтры или период." />
          : <EmptyState title="Платежей пока нет" description="Регулярные платежи добавляет администратор." />)
        : <div className={styles.list}>{currentData.items.map((item) => <PaymentCard key={item.id} title={item.title} amount={item.amount} currency={item.currency} dueDate={item.due_date} paidDate={item.paid_date} status={toPaymentDisplayStatus(item.state)} detailsHref={`/payments/${item.id}`} />)}</div>}
      {currentData.total > PAGE_SIZE && <nav className={styles.pagination} aria-label="Страницы платежей">
        <Button variant="secondary" disabled={page <= 1 || isFetching} onClick={() => setPage(page - 1)}>Назад</Button>
        <span>Страница {page} из {Math.ceil(currentData.total / PAGE_SIZE)}</span>
        <Button variant="secondary" disabled={page >= Math.ceil(currentData.total / PAGE_SIZE) || isFetching} onClick={() => setPage(page + 1)}>Далее</Button>
      </nav>}
    </>}
  </main>
}
