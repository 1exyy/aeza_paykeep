import { Link, useSearchParams } from 'react-router'
import { DeleteUser, EditUserTelegram, SetUserPassword, telegramLabel, useGetUsersQuery } from '@/features/manage-user'
import { getHttpStatus } from '@/shared/api'
import { Button, EmptyState, ErrorState, LoadingState } from '@/shared/ui'
import styles from './UsersPage.module.css'

const PAGE_SIZE = 50

export function UsersPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const rawPage = Number(searchParams.get('page'))
  const page = Number.isSafeInteger(rawPage) && rawPage > 0 ? rawPage : 1
  const { currentData, error, isFetching, refetch } = useGetUsersQuery({ limit: PAGE_SIZE, offset: (page - 1) * PAGE_SIZE })
  const setPage = (next: number) => setSearchParams(next === 1 ? {} : { page: String(next) })
  return <main className={styles.page}>
    <Link to="/payments">К платежам</Link>
    <div className={styles.heading}><h1>Пользователи</h1><Link className={styles.newLink} to="/users/new">Добавить пользователя</Link></div>
    {!currentData && isFetching && <LoadingState />}
    {!currentData && error && <ErrorState title={getHttpStatus(error) === 403 ? 'Нет доступа' : 'Не удалось загрузить пользователей'} onRetry={getHttpStatus(error) === 403 ? undefined : () => void refetch()} />}
    {currentData && <>
      {isFetching && <p role="status">Обновляем список…</p>}
      {error && <p className={styles.warning} role="alert">Не удалось обновить данные. Показан последний подтверждённый список. <Button variant="secondary" onClick={() => void refetch()}>Повторить</Button></p>}
      {currentData.total === 0 ? <EmptyState title="Пользователей пока нет" description="Добавьте обычного пользователя." /> : <div className={styles.list}>
        {currentData.items.map((user) => <article key={user.id} className={styles.card}>
          <h2>{user.login}</h2>
          <p>Обычный пользователь</p>
          <p>Telegram: {telegramLabel(user)}</p>
          {!user.is_protected && <div className={styles.actions}>
            <EditUserTelegram user={user} onUncertain={() => void refetch()} />
            <SetUserPassword user={user} onUncertain={() => void refetch()} />
            <DeleteUser id={user.id} login={user.login} onUncertain={() => void refetch()} />
          </div>}
        </article>)}
      </div>}
      {currentData.total > PAGE_SIZE && <nav className={styles.pagination} aria-label="Страницы пользователей">
        <Button variant="secondary" disabled={page <= 1 || isFetching} onClick={() => setPage(page - 1)}>Назад</Button>
        <span>Страница {page} из {Math.ceil(currentData.total / PAGE_SIZE)}</span>
        <Button variant="secondary" disabled={page >= Math.ceil(currentData.total / PAGE_SIZE) || isFetching} onClick={() => setPage(page + 1)}>Далее</Button>
      </nav>}
    </>}
  </main>
}
