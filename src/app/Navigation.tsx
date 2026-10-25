import { useState } from 'react'
import { NavLink, useLocation } from 'react-router'
import type { User } from '@/entities/session'
import { Button, Dialog } from '@/shared/ui'
import styles from './SessionGate.module.css'

type IconName = 'payments' | 'calendar' | 'budget' | 'more'

function NavIcon({ name }: { name: IconName }) {
  const common = { width: 22, height: 22, viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', strokeWidth: 1.8, strokeLinecap: 'round' as const, strokeLinejoin: 'round' as const, 'aria-hidden': true as const }
  if (name === 'payments') return <svg {...common}><rect x="3" y="5" width="18" height="14" rx="2" /><path d="M3 9h18M7 15h4" /></svg>
  if (name === 'calendar') return <svg {...common}><rect x="3" y="5" width="18" height="16" rx="2" /><path d="M7 3v4M17 3v4M3 10h18M8 15h3" /></svg>
  if (name === 'budget') return <svg {...common}><rect x="3" y="4" width="18" height="16" rx="2" /><path d="M7 16v-4M12 16V8M17 16v-6" /></svg>
  return <svg {...common}><circle cx="5" cy="12" r="1" /><circle cx="12" cy="12" r="1" /><circle cx="19" cy="12" r="1" /></svg>
}

const primaryLinks = [
  { to: '/payments', label: 'Платежи', icon: 'payments' },
  { to: '/calendar', label: 'Календарь', icon: 'calendar' },
  { to: '/budget', label: 'Бюджет', icon: 'budget' },
] as const

function MoreMenu({ user, onLogout, isLoggingOut, logoutError, mobile }: {
  user: User
  onLogout: () => Promise<void>
  isLoggingOut: boolean
  logoutError?: string
  mobile: boolean
}) {
  const [open, setOpen] = useState(false)
  const { pathname } = useLocation()
  const isActive = ['/recurring-payments', '/users', '/audit-log', '/deliveries', '/settings', '/password'].some((path) => pathname.startsWith(path))
  const isAdmin = user.role === 'admin'

  return <Dialog
    open={open}
    onOpenChange={setOpen}
    title="Ещё"
    description={`Вы вошли как ${user.login}.`}
    trigger={<button type="button" className={`${mobile ? styles.mobileItem : styles.desktopItem} ${isActive ? styles.activeItem : ''}`} aria-label="Ещё" aria-current={isActive ? 'page' : undefined}>{mobile && <NavIcon name="more" />}<span>Ещё</span></button>}
  >
    <nav className={styles.moreLinks} aria-label="Дополнительные разделы">
      {isAdmin && <>
        <NavLink to="/recurring-payments" onClick={() => setOpen(false)}>Регулярные платежи</NavLink>
        <NavLink to="/users" onClick={() => setOpen(false)}>Пользователи</NavLink>
        <NavLink to="/audit-log" onClick={() => setOpen(false)}>Журнал действий</NavLink>
        <NavLink to="/deliveries" onClick={() => setOpen(false)}>Доставки уведомлений</NavLink>
        <NavLink to="/settings/notifications" onClick={() => setOpen(false)}>Настройки уведомлений</NavLink>
      </>}
      <NavLink to="/password" onClick={() => setOpen(false)}>Сменить пароль</NavLink>
    </nav>
    <div className={styles.moreLogout}>
      <Button variant="secondary" pending={isLoggingOut} onClick={() => void onLogout()}>Выйти</Button>
      {logoutError && <p className={styles.logoutError} role="alert">{logoutError}</p>}
    </div>
  </Dialog>
}

export function Navigation({ user, onLogout, isLoggingOut, logoutError }: {
  user: User
  onLogout: () => Promise<void>
  isLoggingOut: boolean
  logoutError?: string
}) {
  return <>
    <nav className={styles.desktopNav} aria-label="Основная навигация">
      {primaryLinks.map(({ to, label }) => <NavLink key={to} to={to} className={({ isActive }) => `${styles.desktopItem} ${isActive ? styles.activeItem : ''}`}>{label}</NavLink>)}
      <MoreMenu user={user} onLogout={onLogout} isLoggingOut={isLoggingOut} logoutError={logoutError} mobile={false} />
    </nav>
    <nav className={styles.mobileNav} aria-label="Основная навигация">
      {primaryLinks.map(({ to, label, icon }) => <NavLink key={to} to={to} className={({ isActive }) => `${styles.mobileItem} ${isActive ? styles.activeItem : ''}`}><NavIcon name={icon} /><span>{label}</span></NavLink>)}
      <MoreMenu user={user} onLogout={onLogout} isLoggingOut={isLoggingOut} logoutError={logoutError} mobile />
    </nav>
  </>
}
