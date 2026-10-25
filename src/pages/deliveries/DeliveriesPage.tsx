import { useState, type FormEvent } from 'react'
import { Link, useSearchParams } from 'react-router'
import { useGetDeliveriesQuery, type Channel, type DeliveryStatus } from '@/entities/delivery'
import { getHttpStatus } from '@/shared/api'
import { Button, EmptyState, ErrorState, Field, LoadingState, Select } from '@/shared/ui'
import styles from './DeliveriesPage.module.css'

const PAGE_SIZE = 50
const channels: Channel[] = ['telegram', 'email', 'webhook', 'extra']
const statuses: DeliveryStatus[] = ['pending', 'sending', 'sent', 'failed', 'unknown']
const channelLabels: Record<Channel, string> = { telegram: 'Telegram', email: 'Email', webhook: 'Webhook', extra: 'Дополнительный канал' }
const statusLabels: Record<DeliveryStatus, string> = { pending: 'Ожидает', sending: 'Отправляется', sent: 'Отправлено сервером', failed: 'Ошибка', unknown: 'Статус неизвестен' }
const channelOptions = [{ value: 'all', label: 'Все каналы' }, ...channels.map((value) => ({ value, label: channelLabels[value] }))]
const statusOptions = [{ value: 'all', label: 'Все статусы' }, ...statuses.map((value) => ({ value, label: statusLabels[value] }))]

export function DeliveriesPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const rawPage = Number(searchParams.get('page'))
  const page = Number.isSafeInteger(rawPage) && rawPage > 0 ? rawPage : 1
  const rawChannel = searchParams.get('channel')
  const rawStatus = searchParams.get('status')
  const rawOccurrence = searchParams.get('occurrence_id')
  const channel = channels.find((value) => value === rawChannel)
  const status = statuses.find((value) => value === rawStatus)
  const occurrenceId = rawOccurrence && Number.isSafeInteger(Number(rawOccurrence)) && Number(rawOccurrence) > 0 ? Number(rawOccurrence) : undefined
  const [draftChannel, setDraftChannel] = useState(rawChannel ?? '')
  const [draftStatus, setDraftStatus] = useState(rawStatus ?? '')
  const [draftOccurrence, setDraftOccurrence] = useState(rawOccurrence ?? '')
  const [validationError, setValidationError] = useState<string>()
  const { currentData, error, isFetching, refetch } = useGetDeliveriesQuery({ limit: PAGE_SIZE, offset: (page - 1) * PAGE_SIZE, ...(channel && { channel }), ...(status && { status }), ...(occurrenceId && { occurrence_id: occurrenceId }) })

  function applyFilters(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (draftOccurrence && (!Number.isSafeInteger(Number(draftOccurrence)) || Number(draftOccurrence) < 1)) return setValidationError('ID периода должен быть положительным целым числом.')
    setValidationError(undefined)
    setSearchParams({ ...(draftChannel && { channel: draftChannel }), ...(draftStatus && { status: draftStatus }), ...(draftOccurrence && { occurrence_id: draftOccurrence }) })
  }
  const setPage = (next: number) => {
    const params = new URLSearchParams(searchParams)
    if (next === 1) params.delete('page')
    else params.set('page', String(next))
    setSearchParams(params)
  }

  return <main className={styles.page}>
    <Link to="/payments">К платежам</Link>
    <h1>Доставки уведомлений</h1>
    <p>Здесь показаны состояния, которые сообщил сервер. Окончательное получение проверяется отдельно у адресата.</p>
    <form className={styles.filters} onSubmit={applyFilters}>
      <Select label="Канал" value={draftChannel || 'all'} onValueChange={(value) => setDraftChannel(value === 'all' ? '' : value)} options={channelOptions} />
      <Select label="Статус" value={draftStatus || 'all'} onValueChange={(value) => setDraftStatus(value === 'all' ? '' : value)} options={statusOptions} />
      <Field label="ID периода" type="number" min="1" step="1" value={draftOccurrence} onChange={(event) => setDraftOccurrence(event.target.value)} />
      <Button type="submit">Показать</Button>
    </form>
    {validationError && <p role="alert" className={styles.warning}>{validationError}</p>}
    {!currentData && isFetching && <LoadingState />}
    {!currentData && error && <ErrorState title={getHttpStatus(error) === 403 ? 'Нет доступа' : 'Не удалось загрузить доставки'} onRetry={getHttpStatus(error) === 403 ? undefined : () => void refetch()} />}
    {currentData && <>
      {isFetching && <p role="status">Обновляем доставки…</p>}
      {error && <p role="alert" className={styles.warning}>Не удалось обновить данные. Показаны последние подтверждённые сервером статусы. <Button variant="secondary" onClick={() => void refetch()}>Повторить</Button></p>}
      {currentData.total === 0 ? <EmptyState title="Доставок нет" description="Для выбранных фильтров сервер не вернул доставок." /> : <ol className={styles.list}>{currentData.items.map((item) => <li key={item.id} className={styles.card}>
        <strong>{channelLabels[item.channel]} · {statusLabels[item.status]}</strong>
        <span>{item.notification_type} · {item.created_at.replace('T', ' ')}</span>
        {item.occurrence_id && <Link to={`/payments/${item.occurrence_id}`}>Период #{item.occurrence_id}</Link>}
        <span>Попыток: {item.attempts}</span>
        {item.last_error && <span>Последняя ошибка: {item.last_error}</span>}
      </li>)}</ol>}
      {currentData.total > PAGE_SIZE && <nav className={styles.pagination} aria-label="Страницы доставок"><Button variant="secondary" disabled={page <= 1 || isFetching} onClick={() => setPage(page - 1)}>Назад</Button><span>Страница {page} из {Math.ceil(currentData.total / PAGE_SIZE)}</span><Button variant="secondary" disabled={page >= Math.ceil(currentData.total / PAGE_SIZE) || isFetching} onClick={() => setPage(page + 1)}>Далее</Button></nav>}
    </>}
  </main>
}
