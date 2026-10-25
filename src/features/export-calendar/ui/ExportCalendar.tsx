import { useState } from 'react'
import { useExportCalendarMutation } from '@/entities/payment-occurrence'
import { getSafeErrorMessage } from '@/shared/api'
import { Button, Select } from '@/shared/ui'
import { exportRange } from '../model/range'
import styles from './ExportCalendar.module.css'

type Scope = 'month' | 'year'
const scopes = [{ value: 'month', label: 'Этот месяц' }, { value: 'year', label: 'Весь год' }]

/** Download the team's calendar as CSV (spreadsheets) or .ics (calendar apps). */
export function ExportCalendar({ month }: { month: string }) {
  const [scope, setScope] = useState<Scope>('month')
  const [error, setError] = useState<string>()
  const [exportCalendar, { isLoading, originalArgs }] = useExportCalendarMutation()

  const download = async (format: 'csv' | 'ics') => {
    setError(undefined)
    try {
      const file = await exportCalendar({ format, ...exportRange(month, scope) }).unwrap()
      const anchor = document.createElement('a')
      anchor.href = file.url
      anchor.download = file.fileName
      document.body.append(anchor)
      anchor.click()
      anchor.remove()
      window.setTimeout(() => URL.revokeObjectURL(file.url), 60_000)
    } catch (requestError) {
      setError(getSafeErrorMessage(requestError, 'Не удалось выгрузить календарь. Попробуйте ещё раз.'))
    }
  }

  return <section className={styles.panel} aria-label="Выгрузка календаря">
    <div className={styles.scope}>
      <Select label="Выгрузить" value={scope} onValueChange={(value) => setScope(value === 'year' ? 'year' : 'month')} options={scopes} />
    </div>
    <Button variant="secondary" pending={isLoading && originalArgs?.format === 'csv'} disabled={isLoading} onClick={() => void download('csv')}>Скачать .csv</Button>
    <Button variant="secondary" pending={isLoading && originalArgs?.format === 'ics'} disabled={isLoading} onClick={() => void download('ics')}>Скачать .ics</Button>
    <p className={styles.note}>.csv открывается в Excel и Google Таблицах, .ics — в Google, Apple и Outlook календарях. Повторный импорт .ics обновит события, а не задвоит их.</p>
    {error && <p className={styles.error} role="alert">{error}</p>}
  </section>
}
