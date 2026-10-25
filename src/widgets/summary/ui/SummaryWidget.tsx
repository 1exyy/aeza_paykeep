import { useEffect, useState } from 'react'
import { useForm } from 'react-hook-form'
import { useSearchParams } from 'react-router'
import { useGetSummaryQuery, type CurrencyTotals } from '@/entities/payment-occurrence'
import { formatDateOnly, isDateOnly, shiftDateOnly } from '@/shared/lib/date'
import type { Currency } from '@/shared/lib/money'
import { Button, ErrorState, Field, LoadingState } from '@/shared/ui'
import { SummaryPanel } from './SummaryPanel'
import styles from './SummaryWidget.module.css'

type Range = { from: string; to: string }

function currentMonth(today: string): Range {
  const [year, month] = today.split('-').map(Number)
  const last = new Date(Date.UTC(year!, month!, 0)).getUTCDate()
  return { from: `${year}-${String(month).padStart(2, '0')}-01`, to: `${year}-${String(month).padStart(2, '0')}-${String(last).padStart(2, '0')}` }
}

function totalsRecord(currencies: CurrencyTotals[]): Record<Currency, { accrued: string; paid: string; unpaid: string; overdue: string }> | undefined {
  const codes: Currency[] = ['RUB', 'USD', 'EUR']
  if (currencies.length !== 3 || new Set(currencies.map(({ currency }) => currency)).size !== 3) return undefined
  const result = {} as Record<Currency, { accrued: string; paid: string; unpaid: string; overdue: string }>
  for (const code of codes) {
    const entry = currencies.find(({ currency }) => currency === code)
    if (!entry) return undefined
    result[code] = { accrued: entry.total, paid: entry.paid, unpaid: entry.unpaid, overdue: entry.overdue }
  }
  return result
}

type Props = {
  today: string
  timezoneLabel: string
  /** «Подробнее»: show the payments due in the summary range. */
  onDetails?: (range: Range) => void
}

export function SummaryWidget({ today, timezoneLabel, onDetails }: Props) {
  const defaultRange = currentMonth(today)
  const [searchParams, setSearchParams] = useSearchParams()
  const fromParam = searchParams.get('from')
  const toParam = searchParams.get('to')
  const range = fromParam && toParam && isDateOnly(fromParam) && isDateOnly(toParam) && fromParam <= toParam && toParam <= shiftDateOnly(fromParam, 731)
    ? { from: fromParam, to: toParam } : defaultRange
  const [rangeError, setRangeError] = useState<string>()
  const { register, handleSubmit, reset } = useForm<Range>({ defaultValues: range })
  useEffect(() => reset({ from: range.from, to: range.to }), [range.from, range.to, reset])
  const { currentData, error, isFetching, refetch } = useGetSummaryQuery(range)
  const totals = currentData ? totalsRecord(currentData.currencies) : undefined

  const submit = handleSubmit((values) => {
    setRangeError(undefined)
    if (!isDateOnly(values.from) || !isDateOnly(values.to) || values.from > values.to || values.to > shiftDateOnly(values.from, 731)) {
      setRangeError('Укажите корректный диапазон не длиннее 731 дня.')
      return
    }
    const next = new URLSearchParams(searchParams)
    next.set('from', values.from)
    next.set('to', values.to)
    setSearchParams(next)
  })

  return <section className={styles.widget} aria-label="Сводка">
    <form className={styles.range} onSubmit={submit} noValidate>
      <Field label="Сроки с" type="date" {...register('from')} />
      <Field label="Сроки по" type="date" {...register('to')} />
      <Button type="submit" variant="secondary">Показать</Button>
    </form>
    {rangeError && <p className={styles.error} role="alert">{rangeError}</p>}
    {!currentData && isFetching && <LoadingState />}
    {!currentData && error && <ErrorState title="Не удалось загрузить сводку" onRetry={() => void refetch()} />}
    {currentData && !totals && <ErrorState title="Не удалось отобразить сводку" onRetry={() => void refetch()} />}
    {currentData && totals && <>
      {isFetching && <p role="status">Обновляем сводку…</p>}
      {error && <p className={styles.warning} role="alert">Не удалось обновить сводку. Показаны последние подтверждённые суммы. <Button variant="secondary" onClick={() => void refetch()}>Повторить</Button></p>}
      <SummaryPanel periodLabel={`${formatDateOnly(currentData.from)} — ${formatDateOnly(currentData.to)}`} timezoneLabel={timezoneLabel} totalsByCurrency={totals} />
      {onDetails && <div className={styles.details}><Button variant="secondary" onClick={() => onDetails({ from: currentData.from, to: currentData.to })}>Подробнее: платежи за период</Button></div>}
    </>}
  </section>
}
