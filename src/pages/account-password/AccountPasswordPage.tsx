import { useState } from 'react'
import { Link, useOutletContext } from 'react-router'
import type { SessionContext } from '@/app/SessionGate'
import { ChangePasswordForm } from '@/features/change-password'
import { useUpdateDmNotificationsMutation } from '@/entities/session'
import { getSafeErrorMessage } from '@/shared/api'
import styles from './AccountPasswordPage.module.css'

/** Personal notification preference and password settings. */
export function AccountPasswordPage() {
  const { user } = useOutletContext<SessionContext>()
  const [done, setDone] = useState(false)
  const [updateDm, { isLoading: isSavingDm }] = useUpdateDmNotificationsMutation()
  const [dmError, setDmError] = useState<string>()
  const changeDm = async (enabled: boolean) => {
    setDmError(undefined)
    try {
      await updateDm(enabled).unwrap()
    } catch (error) {
      setDmError(getSafeErrorMessage(error, 'Не удалось сохранить настройку уведомлений.'))
    }
  }
  return <main className={styles.page}>
    <Link to="/payments">К платежам</Link>
    <h1>Личные настройки</h1>
    <section className={styles.section} aria-labelledby="dm-heading">
      <h2 id="dm-heading">Уведомления в Telegram</h2>
      <label className={styles.toggle}>
        <input type="checkbox" checked={user.telegram_dm_enabled} disabled={isSavingDm} onChange={(event) => void changeDm(event.target.checked)} />
        Получать напоминания в личные сообщения
      </label>
      <p>Настройка действует только для вас. Уведомления в чате команды продолжат приходить.</p>
      {!user.telegram_linked && <p>Чтобы получать сообщения, сначала откройте бота и отправьте ему /start.</p>}
      {dmError && <p role="alert" className={styles.error}>{dmError}</p>}
    </section>
    <section className={styles.section} aria-labelledby="password-heading">
      <h2 id="password-heading">Сменить пароль</h2>
      <p>Учётная запись {user.login}. После смены остальные устройства выйдут из приложения.</p>
      {done ? <p className={styles.success} role="status">Пароль изменён.</p> : <ChangePasswordForm onChanged={() => setDone(true)} />}
    </section>
  </main>
}
