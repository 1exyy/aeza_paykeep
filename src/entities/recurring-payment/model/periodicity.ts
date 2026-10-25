import type { Periodicity } from '../api/recurringApi'

export const periodicityOptions: { value: Periodicity; label: string }[] = [
  { value: 'monthly', label: 'Ежемесячно' },
  { value: 'weekly', label: 'Еженедельно' },
  { value: 'daily', label: 'Ежедневно' },
  { value: 'every_n_days', label: 'Каждые N дней' },
  { value: 'once', label: 'Разовый' },
]

export function isPeriodicity(value: string): value is Periodicity {
  return periodicityOptions.some((option) => option.value === value)
}

export function periodicityLabel(item: { periodicity: Periodicity; interval_days?: number | null }): string {
  if (item.periodicity === 'every_n_days') return `Каждые ${item.interval_days ?? 'N'} дн.`
  return periodicityOptions.find(({ value }) => value === item.periodicity)?.label ?? item.periodicity
}

/** Text field value → interval for «каждые N дней», or an error message. */
export function parseInterval(value: string): number | string {
  if (!/^\d{1,3}$/.test(value.trim())) return 'Укажите целое число дней от 1 до 365'
  const days = Number(value.trim())
  return days >= 1 && days <= 365 ? days : 'Укажите целое число дней от 1 до 365'
}

export function statusLabel(item: { status: 'active' | 'stopped'; completed?: boolean }): string {
  if (item.status === 'active') return 'Действует'
  return item.completed ? 'Завершён (оплачен)' : 'Прекращён'
}
