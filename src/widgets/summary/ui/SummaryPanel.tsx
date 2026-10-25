import { useState } from 'react'
import type { Currency } from '@/shared/lib/money'
import { MoneyValue } from '@/shared/ui'
import styles from './SummaryPanel.module.css'

type Totals = { accrued: string; paid: string; unpaid: string; overdue: string }
type Props = { periodLabel: string; timezoneLabel: string; totalsByCurrency: Record<Currency, Totals> }
const currencies: Currency[] = ['RUB', 'USD', 'EUR']

export function SummaryPanel({ periodLabel, timezoneLabel, totalsByCurrency }: Props) {
  const [currency, setCurrency] = useState<Currency>('RUB')
  const totals = totalsByCurrency[currency]

  return <section className={styles.panel} aria-labelledby="summary-title">
    <div className={styles.heading}>
      <div><p className={styles.eyebrow}>По срокам оплаты</p><h2 id="summary-title">Сводка</h2></div>
      <p className={styles.period}>{periodLabel}</p>
    </div>
    <p className={styles.zone}>Даты — {timezoneLabel}</p>
    <div className={styles.currencies} role="group" aria-label="Валюта сводки">
      {currencies.map((code) => <button key={code} type="button" className={currency === code ? styles.selected : styles.currency} aria-pressed={currency === code} onClick={() => setCurrency(code)}>{code}</button>)}
    </div>
    <dl className={styles.totals}>
      <div><dt>Начислено</dt><dd><MoneyValue value={totals.accrued} currency={currency} /></dd></div>
      <div><dt>Оплачено</dt><dd><MoneyValue value={totals.paid} currency={currency} /></dd></div>
      <div><dt>Не оплачено</dt><dd><MoneyValue value={totals.unpaid} currency={currency} /></dd></div>
      <div><dt>Просрочено</dt><dd><MoneyValue value={totals.overdue} currency={currency} /></dd></div>
    </dl>
    <p className={styles.note}>Просрочено — часть неоплаченной суммы.</p>
  </section>
}
