import { Outlet, useOutletContext } from 'react-router'
import { AccessDeniedState } from '@/shared/ui'
import type { SessionContext } from './SessionGate'

export function AdminGate() {
  const context = useOutletContext<SessionContext>()
  if (context.user.role !== 'admin') return <main><AccessDeniedState /></main>
  return <Outlet context={context} />
}
