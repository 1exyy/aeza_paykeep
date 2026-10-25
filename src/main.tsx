import React from 'react'
import ReactDOM from 'react-dom/client'
import '@fontsource/inter/cyrillic-400.css'
import '@fontsource/inter/cyrillic-500.css'
import '@fontsource/inter/cyrillic-600.css'
import '@fontsource/inter/cyrillic-700.css'
import '@fontsource/inter/latin-400.css'
import '@fontsource/inter/latin-500.css'
import '@fontsource/inter/latin-600.css'
import '@fontsource/inter/latin-700.css'
import '@fontsource/exo-2/cyrillic-700.css'
import '@fontsource/exo-2/cyrillic-800.css'
import '@fontsource/exo-2/latin-700.css'
import '@fontsource/exo-2/latin-800.css'
import { App } from '@/app'
import '@/app/styles/tokens.css'
import '@/app/styles/global.css'

async function startApp() {
  if (import.meta.env.DEV && import.meta.env.VITE_MOCK_API === 'true') {
    const { startDemoWorker } = await import('./mocks/browser')
    await startDemoWorker()
  }

  ReactDOM.createRoot(document.getElementById('root')!).render(
    <React.StrictMode>
      <App />
    </React.StrictMode>,
  )
}

void startApp()
