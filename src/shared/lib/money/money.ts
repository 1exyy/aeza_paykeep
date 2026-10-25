export type Currency = 'RUB' | 'USD' | 'EUR'

// Сумма остаётся десятичной строкой: без float-вычислений и конвертации.
export function formatMoney(value: string, currency: Currency): string {
  if (!/^-?\d+(?:\.\d+)?$/.test(value)) throw new Error('Некорректная сумма')
  const [whole, fraction] = value.split('.')
  const grouped = whole!.replace(/\B(?=(\d{3})+(?!\d))/g, '\u00a0')
  return `${grouped}${fraction === undefined ? '' : `,${fraction}`}\u00a0${currency}`
}
