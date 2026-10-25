import { useState } from 'react'
import { useLoginMutation } from '@/entities/session'
import { LoginForm } from '@/features/login'
import { getApiErrorCode, getHttpStatus, getSafeErrorMessage } from '@/shared/api'
import styles from './LoginPage.module.css'

export function LoginPage({ onAuthenticated }: { onAuthenticated: () => void }) {
  const [login] = useLoginMutation()
  const [submitError, setSubmitError] = useState<string>()

  return <main className={styles.page}>
    <section className={styles.card}>
      <img className={styles.brand} src="/brand/aeza-paykeep.svg" alt="Aéza PayKeep" />
      <h1>Вход</h1>
      <LoginForm
        submitError={submitError}
        onSubmit={async (values) => {
          setSubmitError(undefined)
          try {
            await login(values).unwrap()
            onAuthenticated()
          } catch (error) {
            const code = getApiErrorCode(error)
            if (code === 'invalid_credentials') setSubmitError('Не удалось войти. Проверьте команду, логин и пароль.')
            else if (getHttpStatus(error) === undefined) setSubmitError('Нет соединения с сервером. Попробуйте ещё раз.')
            else setSubmitError(getSafeErrorMessage(error, 'Не удалось выполнить вход. Попробуйте ещё раз.'))
          }
        }}
      />
    </section>
  </main>
}
