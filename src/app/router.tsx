import { createBrowserRouter, Navigate } from 'react-router'
import type { RouteObject } from 'react-router'
import { PaymentDetailsPage } from '@/pages/payment-details'
import { PaymentsPage } from '@/pages/payments'
import { NewRecurringPaymentPage } from '@/pages/new-recurring-payment'
import { EditRecurringPaymentPage } from '@/pages/edit-recurring-payment'
import { RecurringPaymentHistoryPage } from '@/pages/recurring-payment-history'
import { RecurringPaymentsPage } from '@/pages/recurring-payments'
import { NewUserPage } from '@/pages/new-user'
import { UsersPage } from '@/pages/users'
import { CalendarPage } from '@/pages/calendar'
import { BudgetPage } from '@/pages/budget'
import { AuditLogPage } from '@/pages/audit-log'
import { DeliveriesPage } from '@/pages/deliveries'
import { NotificationSettingsPage } from '@/pages/notification-settings'
import { AccountPasswordPage } from '@/pages/account-password'
import { AdminGate } from './AdminGate'
import { SessionGate } from './SessionGate'

const routes: RouteObject[] = [{ path: '/', element: <SessionGate />, children: [
  { index: true, element: <Navigate to="/payments" replace /> },
  { path: 'payments', element: <PaymentsPage /> },
  { path: 'payments/:id', element: <PaymentDetailsPage /> },
  { path: 'calendar', element: <CalendarPage /> },
  { path: 'budget', element: <BudgetPage /> },
  { path: 'password', element: <AccountPasswordPage /> },
  { element: <AdminGate />, children: [
    { path: 'recurring-payments', element: <RecurringPaymentsPage /> },
    { path: 'recurring-payments/new', element: <NewRecurringPaymentPage /> },
    { path: 'recurring-payments/:id/edit', element: <EditRecurringPaymentPage /> },
    { path: 'recurring-payments/:id/history', element: <RecurringPaymentHistoryPage /> },
    { path: 'users', element: <UsersPage /> },
    { path: 'users/new', element: <NewUserPage /> },
    { path: 'audit-log', element: <AuditLogPage /> },
    { path: 'deliveries', element: <DeliveriesPage /> },
    { path: 'settings/notifications', element: <NotificationSettingsPage /> },
  ] },
] }]

if (import.meta.env.DEV) {
  const { DevUiPage } = await import('@/pages/dev-ui')
  routes.unshift({ path: '/_dev/ui', element: <DevUiPage /> })
}

export const router = createBrowserRouter(routes)
