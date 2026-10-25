import { useState } from 'react'
import { Link, Outlet, useNavigate } from 'react-router'
import { useDispatch } from 'react-redux'
import { useGetMeQuery, useLogoutMutation, type User } from '@/entities/session'
import { ApplicationsPage } from '@/pages/applications'
import { ChangePasswordPage } from '@/pages/change-password'
import { LoginPage } from '@/pages/login'
import { getHttpStatus, getSafeErrorMessage, baseApi } from '@/shared/api'
import { useGetConfigQuery, type AppConfig } from '@/shared/config'
import { ErrorState, LoadingState } from '@/shared/ui'
import { Navigation } from './Navigation'
import styles from './SessionGate.module.css'

export type SessionContext = { user: User; config: AppConfig }

function AuthenticatedShell({ user }: { user: User }) {
  const { data: config, error, isLoading, refetch } = useGetConfigQuery()
  const [logout, { isLoading: isLoggingOut }] = useLogoutMutation()
  const [logoutError, setLogoutError] = useState<string>()
  const dispatch = useDispatch()
  const navigate = useNavigate()

  if (isLoading) return <main className={styles.center}><LoadingState /></main>
  if (error || !config) return <main className={styles.center}><ErrorState title="Не удалось получить настройки приложения" onRetry={() => void refetch()} /></main>

  const handleLogout = async () => {
    setLogoutError(undefined)
    try {
      await logout().unwrap()
      dispatch(baseApi.util.resetApiState())
      navigate('/', { replace: true })
    } catch (requestError) {
      setLogoutError(getSafeErrorMessage(requestError, 'Не удалось выйти. Попробуйте ещё раз.'))
    }
  }

  return <div className={styles.shell}>
    <header className={styles.header}>
      <Link className={styles.brand} to="/payments"><img src="/brand/paykeep-wallet.svg" alt="" /><span><b>Aéza</b> PayKeep</span></Link>
      {config.team && <span className={styles.team} title="Команда">{config.team.name}</span>}
      <Navigation user={user} onLogout={handleLogout} isLoggingOut={isLoggingOut} logoutError={logoutError} />
      {import.meta.env.DEV && import.meta.env.VITE_MOCK_API === 'true' && <span className={styles.demoBadge} aria-label="Демо · тестовые данные">Демо</span>}
    </header>
    <Outlet context={{ user, config } satisfies SessionContext} />
  </div>
}

/** The supervisor sees only the applications: no team, no config. */
function SupervisorShell({ user }: { user: User }) {
  const { handleLogout, isLoggingOut, logoutError } = useSignOut()
  return <div className={styles.shell}>
    <header className={styles.header}>
      <span className={styles.brand}><img src="/brand/paykeep-wallet.svg" alt="" /><span><b>Aéza</b> PayKeep</span></span>
      <span className={styles.team} title="Роль">Супервайзер · {user.login}</span>
      <button type="button" className={styles.desktopItem} disabled={isLoggingOut} aria-busy={isLoggingOut || undefined} onClick={() => void handleLogout()}><span>Выйти</span></button>
    </header>
    {logoutError && <p className={styles.logoutError} role="alert">{logoutError}</p>}
    <ApplicationsPage />
  </div>
}

function useSignOut() {
  const [logout, { isLoading: isLoggingOut }] = useLogoutMutation()
  const [logoutError, setLogoutError] = useState<string>()
  const dispatch = useDispatch()
  const navigate = useNavigate()
  const handleLogout = async () => {
    setLogoutError(undefined)
    try {
      await logout().unwrap()
      dispatch(baseApi.util.resetApiState())
      navigate('/', { replace: true })
    } catch (requestError) {
      setLogoutError(getSafeErrorMessage(requestError, 'Не удалось выйти. Попробуйте ещё раз.'))
    }
  }
  return { handleLogout, isLoggingOut, logoutError }
}

function TemporaryPassword({ user, onChanged }: { user: User; onChanged: () => void }) {
  const { handleLogout, isLoggingOut } = useSignOut()
  return <ChangePasswordPage user={user} onChanged={onChanged} onLogout={() => void handleLogout()} isLoggingOut={isLoggingOut} />
}

export function SessionGate() {
  const { data: user, error, isLoading, refetch } = useGetMeQuery()

  if (isLoading) return <main className={styles.center}><LoadingState /></main>
  if (getHttpStatus(error) === 401) return <LoginPage onAuthenticated={() => void refetch()} />
  if (error || !user) return <main className={styles.center}><ErrorState title="Не удалось проверить доступ" onRetry={() => void refetch()} /></main>
  if (user.role === 'supervisor') return <SupervisorShell user={user} />
  if (user.must_change_password) return <TemporaryPassword user={user} onChanged={() => void refetch()} />
  return <AuthenticatedShell user={user} />
}
