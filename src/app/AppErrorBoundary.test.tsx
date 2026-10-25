import { render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { AppErrorBoundary } from './AppErrorBoundary'

afterEach(() => vi.restoreAllMocks())

it('показывает безопасное сообщение при ошибке рендера', () => {
  vi.spyOn(console, 'error').mockImplementation(() => {})
  function Broken(): never { throw new Error('secret-test-value') }

  render(<AppErrorBoundary><Broken /></AppErrorBoundary>)

  expect(screen.getByRole('alert')).toHaveTextContent('Не удалось открыть приложение')
  expect(screen.queryByText('secret-test-value')).not.toBeInTheDocument()
})
