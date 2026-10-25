import { useState, type FormEvent } from 'react'
import { Link, useSearchParams } from 'react-router'
import { useGetAuditEventsQuery } from '@/entities/audit-event'
import { getHttpStatus } from '@/shared/api'
import { Button, EmptyState, ErrorState, Field, LoadingState } from '@/shared/ui'
import styles from './AuditLogPage.module.css'

const PAGE_SIZE = 50
const datePattern = /^\d{4}-\d{2}-\d{2}$/

export function AuditLogPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const rawPage = Number(searchParams.get('page'))
  const page = Number.isSafeInteger(rawPage) && rawPage > 0 ? rawPage : 1
  const action = searchParams.get('action') || undefined
  const from = searchParams.get('from') || undefined
  const to = searchParams.get('to') || undefined
  const rawActor = searchParams.get('actor_id')
  const actorId = rawActor && Number.isSafeInteger(Number(rawActor)) && Number(rawActor) > 0 ? Number(rawActor) : undefined
  const [draftAction, setDraftAction] = useState(action ?? '')
  const [draftActor, setDraftActor] = useState(rawActor ?? '')
  const [draftFrom, setDraftFrom] = useState(from ?? '')
  const [draftTo, setDraftTo] = useState(to ?? '')
  const [validationError, setValidationError] = useState<string>()
  const { currentData, error, isFetching, refetch } = useGetAuditEventsQuery({ limit: PAGE_SIZE, offset: (page - 1) * PAGE_SIZE, ...(action && { action }), ...(actorId && { actor_id: actorId }), ...(from && { from }), ...(to && { to }) })

  function applyFilters(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (draftActor && (!Number.isSafeInteger(Number(draftActor)) || Number(draftActor) < 1)) return setValidationError('ID пользователя должен быть положительным целым числом.')
    if ((draftFrom && !datePattern.test(draftFrom)) || (draftTo && !datePattern.test(draftTo)) || (draftFrom && draftTo && draftFrom > draftTo)) return setValidationError('Проверьте диапазон дат.')
    setValidationError(undefined)
    setSearchParams({ ...(draftAction.trim() && { action: draftAction.trim() }), ...(draftActor && { actor_id: draftActor }), ...(draftFrom && { from: draftFrom }), ...(draftTo && { to: draftTo }) })
  }

  const setPage = (next: number) => {
    const params = new URLSearchParams(searchParams)
    if (next === 1) params.delete('page')
    else params.set('page', String(next))
    setSearchParams(params)
  }

  return <main className={styles.page}>
    <Link to="/payments">К платежам</Link>
    <h1>Журнал действий</h1>
    <form className={styles.filters} onSubmit={applyFilters}>
      <Field label="Действие" value={draftAction} onChange={(event) => setDraftAction(event.target.value)} hint="Точное имя или префикс с точкой, например auth." />
      <Field label="ID пользователя" type="number" min="1" step="1" value={draftActor} onChange={(event) => setDraftActor(event.target.value)} />
      <Field label="С даты" type="date" value={draftFrom} onChange={(event) => setDraftFrom(event.target.value)} />
      <Field label="По дату" type="date" value={draftTo} onChange={(event) => setDraftTo(event.target.value)} />
      <Button type="submit">Показать</Button>
    </form>
    {validationError && <p role="alert" className={styles.warning}>{validationError}</p>}
    {!currentData && isFetching && <LoadingState />}
    {!currentData && error && <ErrorState title={getHttpStatus(error) === 403 ? 'Нет доступа' : 'Не удалось загрузить журнал'} onRetry={getHttpStatus(error) === 403 ? undefined : () => void refetch()} />}
    {currentData && <>
      {isFetching && <p role="status">Обновляем журнал…</p>}
      {error && <p role="alert" className={styles.warning}>Не удалось обновить журнал. Показаны последние подтверждённые данные. <Button variant="secondary" onClick={() => void refetch()}>Повторить</Button></p>}
      {currentData.total === 0 ? <EmptyState title="Записей нет" description="Для этих фильтров сервер не вернул событий." /> : <ol className={styles.list}>
        {currentData.items.map((item) => <li key={item.id} className={styles.card}>
          <strong>{item.action}</strong>
          <span>{item.result === 'success' ? 'Успешно' : 'Ошибка'} · {item.source} · {item.at.replace('T', ' ')}</span>
          <span>Инициатор: {item.actor?.login ?? 'Система'}</span>
          {item.object_type && <span>Объект: {item.object_type}{item.object_id ? ` #${item.object_id}` : ''}</span>}
        </li>)}
      </ol>}
      {currentData.total > PAGE_SIZE && <nav className={styles.pagination} aria-label="Страницы журнала">
        <Button variant="secondary" disabled={page <= 1 || isFetching} onClick={() => setPage(page - 1)}>Назад</Button>
        <span>Страница {page} из {Math.ceil(currentData.total / PAGE_SIZE)}</span>
        <Button variant="secondary" disabled={page >= Math.ceil(currentData.total / PAGE_SIZE) || isFetching} onClick={() => setPage(page + 1)}>Далее</Button>
      </nav>}
    </>}
  </main>
}
