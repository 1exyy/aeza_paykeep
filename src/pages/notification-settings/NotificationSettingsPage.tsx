import { Link } from 'react-router'
import { NotificationSettingsForms, useGetNotificationSettingsQuery } from '@/features/manage-notification-settings'
import { getHttpStatus } from '@/shared/api'
import { ErrorState, LoadingState } from '@/shared/ui'
import styles from './NotificationSettingsPage.module.css'

export function NotificationSettingsPage() {
  const { data, error, isLoading, refetch } = useGetNotificationSettingsQuery()
  return <main className={styles.page}>
    <Link to="/payments">К платежам</Link>
    <h1>Настройки уведомлений</h1>
    {data && <p className={styles.meta}>{data.updated_at
      ? `Изменены ${data.updated_at.slice(0, 16).replace('T', ' ')}${data.updated_by ? ` — ${data.updated_by}` : ''}. Применяются без перезапуска.`
      : 'Сейчас действуют значения из .env на сервере. Сохранённые здесь значения их заменят.'}</p>}
    {isLoading && <LoadingState />}
    {error && <ErrorState title={getHttpStatus(error) === 403 ? 'Нет доступа' : 'Не удалось загрузить настройки'} onRetry={getHttpStatus(error) === 403 ? undefined : () => void refetch()} />}
    {data && <NotificationSettingsForms key={data.version} settings={data} />}
  </main>
}
