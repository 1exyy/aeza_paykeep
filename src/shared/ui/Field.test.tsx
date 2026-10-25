import { render, screen } from '@testing-library/react'
import { expect, it } from 'vitest'
import { Field } from './Field'

it('сохраняет внешнее описание и объявляет появившуюся ошибку', () => {
  const { rerender } = render(<>
    <p id="external-help">Внешняя подсказка</p>
    <Field label="Пример поля" hint="Подпись поля" aria-describedby="external-help" />
  </>)

  const input = screen.getByRole('textbox', { name: 'Пример поля' })
  expect(input.getAttribute('aria-describedby')?.split(' ')).toEqual([
    'external-help', screen.getByText('Подпись поля').id,
  ])

  rerender(<>
    <p id="external-help">Внешняя подсказка</p>
    <Field label="Пример поля" hint="Подпись поля" error="Исправьте значение" aria-describedby="external-help" />
  </>)

  expect(input).toHaveAttribute('aria-invalid', 'true')
  expect(screen.getByRole('alert')).toHaveTextContent('Исправьте значение')
  expect(input.getAttribute('aria-describedby')?.split(' ')).toEqual([
    'external-help', screen.getByText('Подпись поля').id, screen.getByRole('alert').id,
  ])
})
