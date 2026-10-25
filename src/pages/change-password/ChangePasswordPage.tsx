import type { User } from '@/entities/session'
import { ChangePasswordForm } from '@/features/change-password'
import { Button } from '@/shared/ui'
import styles from './ChangePasswordPage.module.css'

/** Shown instead of the app while the account has a temporary password. */
export function ChangePasswordPage({ user, onChanged, onLogout, isLoggingOut }: { user: User; onChanged: () => void; onLogout: () => void; isLoggingOut: boolean }) {
  return <main className={styles.page}>
    <section className={styles.card}>
      <h1>Смените пароль</h1>
      <p>Вы вошли как {user.login} с временным паролем. Задайте свой пароль, чтобы продолжить.</p>
      <ChangePasswordForm onChanged={onChanged} />
      <Button variant="secondary" pending={isLoggingOut} onClick={onLogout}>Выйти</Button>
    </section>
  </main>
}
