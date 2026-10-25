import { useState } from 'react'
import { useOutletContext, useSearchParams } from 'react-router'
import type { SessionContext } from '@/app/SessionGate'
import { useGetBudgetQuery } from '@/entities/payment-occurrence'
import { formatDateOnly } from '@/shared/lib/date'
import { formatMoney } from '@/shared/lib/money'
import { Button, ErrorState, LoadingState, Select } from '@/shared/ui'
import styles from './BudgetPage.module.css'

const currencies = ['RUB', 'USD', 'EUR'] as const
const monthNames = ['январь', 'февраль', 'март', 'апрель', 'май', 'июнь', 'июль', 'август', 'сентябрь', 'октябрь', 'ноябрь', 'декабрь']
const periodOptions = [{ value: 'month', label: 'Месяц' }, { value: 'year', label: 'Год' }]
const monthOptions = monthNames.map((label, index) => ({ value: String(index + 1), label }))

function BudgetControls({ period, year, month, onApply }: { period: 'month' | 'year'; year: number; month: number; onApply: (period: 'month' | 'year', year: number, month: number) => void }) {
  const [inputError, setInputError] = useState<string>()
  const [draftPeriod, setDraftPeriod] = useState<'month' | 'year'>(period)
  const [draftYear, setDraftYear] = useState(String(year))
  const [draftMonth, setDraftMonth] = useState(String(month))
  return <><form className={styles.controls} onSubmit={(event) => {
      event.preventDefault()
      setInputError(undefined)
      const selectedYear = Number(draftYear)
      const selectedMonth = Number(draftMonth)
      if (!Number.isSafeInteger(selectedYear) || selectedYear < 2000 || selectedYear > 2100 || (draftPeriod === 'month' && (!Number.isSafeInteger(selectedMonth) || selectedMonth < 1 || selectedMonth > 12))) {
        setInputError('Укажите год от 2000 до 2100 и месяц от 1 до 12.')
        return
      }
      onApply(draftPeriod, selectedYear, selectedMonth)
    }}>
      <Select label="Период" value={draftPeriod} onValueChange={(value) => setDraftPeriod(value as 'month' | 'year')} options={periodOptions} />
      <label>Год<input type="number" min="2000" max="2100" value={draftYear} onChange={(event) => setDraftYear(event.target.value)} /></label>
      {draftPeriod === 'month' && <Select label="Месяц" value={draftMonth} onValueChange={setDraftMonth} options={monthOptions} />}
      <Button type="submit" variant="secondary">Показать</Button>
    </form>
    {inputError && <p className={styles.error} role="alert">{inputError}</p>}
  </>
}

export function BudgetPage() {
  const { config } = useOutletContext<SessionContext>()
  const [params, setParams] = useSearchParams()
  const currentYear = Number(config.today.slice(0, 4))
  const currentMonth = Number(config.today.slice(5, 7))
  const period = params.get('period') === 'year' ? 'year' : 'month'
  const rawYear = Number(params.get('year'))
  const year = Number.isSafeInteger(rawYear) && rawYear >= 2000 && rawYear <= 2100 ? rawYear : currentYear
  const rawMonth = Number(params.get('month'))
  const month = Number.isSafeInteger(rawMonth) && rawMonth >= 1 && rawMonth <= 12 ? rawMonth : currentMonth
  const { currentData, error, isFetching, refetch } = useGetBudgetQuery(period === 'month' ? { period, year, month } : { period, year })
  const validCurrencies = currentData?.currencies.length === 3 && new Set(currentData.currencies.map(({ currency }) => currency)).size === 3

  return <main className={styles.page}>
    <h1>Плановые расходы</h1>
    <p className={styles.zone}>Даты — {config.timezone_label}</p>
    <BudgetControls key={`${period}-${year}-${month}`} period={period} year={year} month={month} onApply={(nextPeriod, nextYear, nextMonth) => setParams(nextPeriod === 'month' ? { period: nextPeriod, year: String(nextYear), month: String(nextMonth) } : { period: nextPeriod, year: String(nextYear) })} />
    {!currentData && isFetching && <LoadingState />}
    {!currentData && error && <ErrorState title="Не удалось загрузить план" onRetry={() => void refetch()} />}
    {currentData && !validCurrencies && <ErrorState title="Не удалось отобразить план" onRetry={() => void refetch()} />}
    {currentData && validCurrencies && <>
      {isFetching && <p role="status">Обновляем план…</p>}
      {error && <p className={styles.warning} role="alert">Не удалось обновить план. Показаны последние подтверждённые суммы. <Button variant="secondary" onClick={() => void refetch()}>Повторить</Button></p>}
      <h2>{formatDateOnly(currentData.from)} — {formatDateOnly(currentData.to)}</h2>
      <div className={styles.cards}>{currencies.map((currency) => {
        const totals = currentData.currencies.find((entry) => entry.currency === currency)
        if (!totals) return null
        return <section key={currency} className={styles.card} aria-label={`План ${currency}`}>
          <h3>{currency}</h3>
          <p className={styles.plannedLabel}>План на период</p>
          <p className={styles.planned}>{formatMoney(totals.planned, currency)}</p>
          <dl>
            <div><dt>Уже оплачено</dt><dd>{formatMoney(totals.existing_paid, currency)}</dd></div>
            <div><dt>Начислено, не оплачено</dt><dd>{formatMoney(totals.existing_unpaid, currency)}</dd></div>
            <div><dt>Расчётные будущие периоды</dt><dd>{formatMoney(totals.projected, currency)}</dd></div>
          </dl>
        </section>
      })}</div>
    </>}
  </main>
}
