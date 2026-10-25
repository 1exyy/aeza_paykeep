import { useState } from 'react'
import { Link, useOutletContext } from 'react-router'
import type { SessionContext } from '@/app/SessionGate'
import { ChangePasswordForm } from '@/features/change-password'
import styles from './AccountPasswordPage.module.css'

/** Anyone changes their own password knowing the current one. */
export function AccountPasswordPage() {
  const { user } = useOutletContext<SessionContext>()
  const [done, setDone] = useState(false)
  return <main className={styles.page}>
    <Link to="/payments">К платежам</Link>
    <h1>Сменить пароль</h1>
    <p>Учётная запись {user.login}. После смены остальные устройства выйдут из приложения.</p>
    {done ? <p className={styles.success} role="status">Пароль изменён.</p> : <ChangePasswordForm onChanged={() => setDone(true)} />}
  </main>
}
