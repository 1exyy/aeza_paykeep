import { expect, it } from 'vitest'
import { formatMoney } from './money'

it('форматирует денежную строку без потери цифр', () => {
  expect(formatMoney('12345678901234567890.123456', 'RUB')).toBe('12\u00a0345\u00a0678\u00a0901\u00a0234\u00a0567\u00a0890,123456\u00a0RUB')
})
