import { useState, type FormEvent } from 'react'
import { Link, useOutletContext } from 'react-router'
import type { SessionContext } from '@/app/SessionGate'
import { ChangePasswordForm } from '@/features/change-password'
import { useUpdateDmNotificationsMutation, useUpdateDmReminderDaysMutation } from '@/entities/session'
import { getSafeErrorMessage } from '@/shared/api'
import { Button } from '@/shared/ui'
import styles from './AccountPasswordPage.module.css'

/** Personal notification preference and password settings. */
export function AccountPasswordPage() {
  const { user } = useOutletContext<SessionContext>()
  const [done, setDone] = useState(false)
  const [updateDm, { isLoading: isSavingDm }] = useUpdateDmNotificationsMutation()
  const [dmError, setDmError] = useState<string>()
  const [days, setDays] = useState(String(user.telegram_dm_days_before))
  const [updateDays, { isLoading: isSavingDays }] = useUpdateDmReminderDaysMutation()
  const [daysError, setDaysError] = useState<string>()
  const [daysSaved, setDaysSaved] = useState(false)
  const changeDm = async (enabled: boolean) => {
    setDmError(undefined)
    try {
      await updateDm(enabled).unwrap()
    } catch (error) {
      setDmError(getSafeErrorMessage(error, 'Не удалось сохранить настройку уведомлений.'))
    }
  }
  const saveDays = async (event: FormEvent) => {
    event.preventDefault()
    setDaysError(undefined)
    setDaysSaved(false)
    const value = Number(days)
    if (!days.trim() || !Number.isInteger(value) || value < 0 || value > 30) {
      setDaysError('Укажите целое число от 0 до 30')
      return
    }
    try {
      await updateDays(value).unwrap()
      setDaysSaved(true)
    } catch (error) {
      setDaysError(getSafeErrorMessage(error, 'Не удалось сохранить срок напоминания.'))
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
      <form className={styles.daysForm} onSubmit={(event) => void saveDays(event)}>
        <label htmlFor="dm-days">За сколько дней до оплаты напомнить в личные сообщения</label>
        <div className={styles.daysControls}>
          <input id="dm-days" type="number" min="0" max="30" step="1" inputMode="numeric" value={days} onChange={(event) => { setDays(event.target.value); setDaysSaved(false); setDaysError(undefined) }} aria-describedby="dm-days-hint" aria-invalid={daysError ? true : undefined} />
          <Button type="submit" pending={isSavingDays} disabled={days.trim() !== '' && Number(days) === user.telegram_dm_days_before}>Сохранить</Button>
        </div>
        <p id="dm-days-hint">От 0 до 30 дней. 0 — в день оплаты. Изменение действует для ещё не отправленных напоминаний.</p>
        {daysError && <p role="alert" className={styles.error}>{daysError}</p>}
        {daysSaved && <p role="status" className={styles.success}>Срок напоминания сохранён.</p>}
      </form>
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
