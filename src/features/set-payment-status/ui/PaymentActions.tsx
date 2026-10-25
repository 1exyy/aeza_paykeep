import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { z } from 'zod'
import { useUpdateOccurrenceMutation, type PaymentOccurrence } from '@/entities/payment-occurrence'
import { getApiErrorCode, getSafeErrorMessage } from '@/shared/api'
import { isDateOnly, shiftDateOnly } from '@/shared/lib/date'
import { Button, Dialog, Field } from '@/shared/ui'
import styles from './PaymentActions.module.css'

type DateValues = { paid_date: string }

export function PaymentActions({ item, today, disabled, onUncertain }: { item: PaymentOccurrence; today: string; disabled: boolean; onUncertain: () => void }) {
  const [dateOpen, setDateOpen] = useState(false)
  const [cancelOpen, setCancelOpen] = useState(false)
  const [requestError, setRequestError] = useState<string>()
  const [conflictNotice, setConflictNotice] = useState<string>()
  const [update, { isLoading }] = useUpdateOccurrenceMutation()
  const { register, handleSubmit, setValue, setError, clearErrors, formState: { errors } } = useForm<DateValues>({ defaultValues: { paid_date: '' } })
  const paid = item.status === 'paid'
  const minDate = shiftDateOnly(item.due_date, -366)

  const submitDate = handleSubmit(async ({ paid_date }) => {
    setRequestError(undefined)
    setConflictNotice(undefined)
    clearErrors()
    const parsed = z.string().refine(isDateOnly, 'Укажите дату оплаты')
      .refine((value) => value >= minDate && value <= today, 'Дата вне допустимого диапазона')
      .safeParse(paid_date)
    if (!parsed.success) {
      setError('paid_date', { message: parsed.error.issues[0]?.message })
      return
    }
    try {
      await update({ id: item.id, patch: paid
        ? { paid_date: parsed.data, expected_version: item.version }
        : { status: 'paid', paid_date: parsed.data, expected_version: item.version } }).unwrap()
      setDateOpen(false)
    } catch (error) {
      if (getApiErrorCode(error) === 'version_conflict') {
        setDateOpen(false)
        setConflictNotice('Платёж изменён другим пользователем. Проверяем актуальные данные.')
      } else setRequestError(getSafeErrorMessage(error, 'Не удалось подтвердить результат. Проверяем актуальные данные.'))
      onUncertain()
    }
  })

  return <div className={styles.actions}>
    {conflictNotice && <p className={styles.error} role="alert">{conflictNotice}</p>}
    <Dialog
      trigger={<Button disabled={disabled}>{paid ? 'Изменить дату оплаты' : 'Отметить оплату'}</Button>}
      title={paid ? 'Изменить дату оплаты' : 'Отметить оплату'}
      description="Укажите фактическую дату оплаты. Срок платежа не изменится."
      open={dateOpen}
      onOpenChange={(next) => {
        if (isLoading) return
        setDateOpen(next)
        setRequestError(undefined)
        setConflictNotice(undefined)
        clearErrors()
        if (next) setValue('paid_date', item.paid_date ?? today)
      }}
    >
      <form className={styles.form} onSubmit={submitDate} noValidate>
        <Field label="Фактическая дата оплаты" type="date" min={minDate} max={today} required {...register('paid_date')} error={errors.paid_date?.message} />
        {requestError && <p className={styles.error} role="alert">{requestError}</p>}
        <Button type="submit" pending={isLoading}>Подтвердить оплату</Button>
      </form>
    </Dialog>
    {paid && <Dialog
      trigger={<Button variant="secondary" disabled={disabled}>Отменить отметку</Button>}
      title="Отменить отметку об оплате?"
      description="Платёж снова станет неоплаченным. Фактическая дата оплаты будет очищена."
      open={cancelOpen}
      onOpenChange={(next) => { if (!isLoading) { setCancelOpen(next); setRequestError(undefined); setConflictNotice(undefined) } }}
      closeLabel="Оставить как есть"
      cancelFirst
    >
      {requestError && <p className={styles.error} role="alert">{requestError}</p>}
      <Button variant="danger" pending={isLoading} onClick={async () => {
        setRequestError(undefined)
        try {
          await update({ id: item.id, patch: { status: 'unpaid', expected_version: item.version } }).unwrap()
          setCancelOpen(false)
        } catch (error) {
          if (getApiErrorCode(error) === 'version_conflict') {
            setCancelOpen(false)
            setConflictNotice('Платёж изменён другим пользователем. Проверяем актуальные данные.')
          } else setRequestError(getSafeErrorMessage(error, 'Не удалось подтвердить результат. Проверяем актуальные данные.'))
          onUncertain()
        }
      }}>Отменить отметку</Button>
    </Dialog>}
  </div>
}
