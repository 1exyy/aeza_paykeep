import { formatMoney, type Currency } from '@/shared/lib/money'
import styles from './MoneyValue.module.css'

export function MoneyValue({ value, currency }: { value: string; currency: Currency }) {
  const formatted = formatMoney(value, currency)
  const numeric = formatted.slice(0, -(currency.length + 1))
  const lastGroupStart = numeric.lastIndexOf('\u00a0') + 1

  return <span className={styles.value}>
    {numeric.slice(0, lastGroupStart)}
    <span className={styles.lastGroup}>{numeric.slice(lastGroupStart)}&nbsp;{currency}</span>
  </span>
}
