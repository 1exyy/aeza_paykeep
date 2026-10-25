import { useEffect } from 'react'
import { Provider } from 'react-redux'
import { RouterProvider } from 'react-router'
import { initializeTelegramShell } from '@/shared/lib/telegram'
import { router } from './router'
import { store } from './store'
import { AppErrorBoundary } from './AppErrorBoundary'

export function App() {
  useEffect(() => initializeTelegramShell(), [])

  return (
    <AppErrorBoundary>
      <Provider store={store}>
        <RouterProvider router={router} />
      </Provider>
    </AppErrorBoundary>
  )
}
