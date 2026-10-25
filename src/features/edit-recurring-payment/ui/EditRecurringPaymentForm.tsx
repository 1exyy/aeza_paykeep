import { useState } from 'react'
import { Controller, useForm } from 'react-hook-form'
import { useNavigate } from 'react-router'
import { AssigneesPicker, isPeriodicity, parseInterval, periodicityOptions, useUpdateRecurringPaymentMutation } from '@/entities/recurring-payment'
import type { AssigneesValue, Periodicity, RecurringPayment, RecurringPaymentPatch, UserRef } from '@/entities/recurring-payment'
import { getApiErrorCode, getSafeErrorMessage } from '@/shared/api'
import { isDateOnly } from '@/shared/lib/date'
import type { Currency } from '@/shared/lib/money'
import { Button, Field, Select } from '@/shared/ui'
import styles from './EditRecurringPaymentForm.module.css'

const moneyPattern = /^\d{1,12}(?:\.\d{1,2})?$/
const currencyOptions = [{ value: 'RUB', label: 'RUB' }, { value: 'USD', label: 'USD' }, { value: 'EUR', label: 'EUR' }]

type Values = { title: string; amount: string; currency: Currency; next_due_date: string; periodicity: Periodicity; interval_days: string }

type Props = {
  payment: RecurringPayment
  today: string
  users: readonly UserRef[]
  usersLoading?: boolean
  usersError?: string
}

const sameIds = (a: readonly number[], b: readonly number[]) => a.length === b.length && [...a].sort().every((id, i) => id === [...b].sort()[i])

/** Admin edits an active payment; changes apply to unpaid periods from today on. */
export function EditRecurringPaymentForm({ payment, today, users, usersLoading, usersError }: Props) {
  const navigate = useNavigate()
  const [update] = useUpdateRecurringPaymentMutation()
  const [submitError, setSubmitError] = useState<string>()
  const initialAssignees: AssigneesValue = { assign_all: payment.assign_all, assignee_ids: payment.assignees.map(({ id }) => id) }
  const [assignees, setAssignees] = useState<AssigneesValue>(initialAssignees)
  const initialDue = payment.next_due_date && payment.next_due_date >= today ? payment.next_due_date : today
  const { register, control, handleSubmit, setError, clearErrors, setFocus, watch, formState: { errors, isSubmitting } } = useForm<Values>({
    defaultValues: {
      title: payment.title,
      amount: payment.amount,
      currency: payment.currency,
      next_due_date: initialDue,
      periodicity: payment.periodicity,
      interval_days: payment.interval_days ? String(payment.interval_days) : '',
    },
  })
  const periodicity = watch('periodicity')

  const submit = handleSubmit(async (values) => {
    setSubmitError(undefined)
    clearErrors()
    const title = values.title.trim()
    if (!title || title.length > 100) return setError('title', { message: 'Название: от 1 до 100 символов' })
    if (!moneyPattern.test(values.amount) || /^0+(?:\.0{1,2})?$/.test(values.amount)) return setError('amount', { message: 'Укажите сумму больше нуля, до двух знаков после точки' })
    if (!isDateOnly(values.next_due_date) || values.next_due_date < today) return setError('next_due_date', { message: 'Дата не может быть раньше сегодняшнего дня' })
    const interval = values.periodicity === 'every_n_days' ? parseInterval(values.interval_days) : null
    if (typeof interval === 'string') {
      setError('interval_days', { message: interval })
      setFocus('interval_days')
      return
    }

    const patch: RecurringPaymentPatch = { id: payment.id, expected_version: payment.version }
    if (title !== payment.title) patch.title = title
    if (Number(values.amount) !== Number(payment.amount)) patch.amount = values.amount
    if (values.currency !== payment.currency) patch.currency = values.currency
    const scheduleChanged = values.periodicity !== payment.periodicity
      || interval !== (payment.interval_days ?? null)
      || values.next_due_date !== initialDue
    if (scheduleChanged) {
      patch.periodicity = values.periodicity
      patch.interval_days = interval
      patch.next_due_date = values.next_due_date
    }
    if (assignees.assign_all !== initialAssignees.assign_all || !sameIds(assignees.assignee_ids, initialAssignees.assignee_ids)) {
      patch.assign_all = assignees.assign_all
      patch.assignee_ids = assignees.assign_all ? [] : assignees.assignee_ids
    }
    if (Object.keys(patch).length === 2) {
      navigate('/recurring-payments')
      return
    }
    try {
      await update(patch).unwrap()
      navigate('/recurring-payments', { replace: true })
    } catch (requestError) {
      setSubmitError(getApiErrorCode(requestError) === 'version_conflict'
        ? 'Платёж уже изменили. Откройте его заново.'
        : getSafeErrorMessage(requestError, 'Не удалось сохранить изменения. Попробуйте ещё раз.'))
    }
  })

  return <form className={styles.form} onSubmit={submit} noValidate>
    <Field label="Название" required {...register('title')} error={errors.title?.message} />
    <Field label="Сумма" required inputMode="decimal" {...register('amount')} error={errors.amount?.message} />
    <Controller name="currency" control={control} render={({ field }) => <Select label="Валюта" required value={field.value} onValueChange={field.onChange} options={currencyOptions} ref={field.ref} />} />
    <Controller name="periodicity" control={control} render={({ field }) => <Select label="Периодичность" required value={field.value} onValueChange={(value) => { if (isPeriodicity(value)) field.onChange(value) }} options={periodicityOptions} ref={field.ref} />} />
    {periodicity === 'every_n_days' && <Field label="Интервал, дней" required inputMode="numeric" hint="От 1 до 365" {...register('interval_days')} error={errors.interval_days?.message} />}
    <Field label={periodicity === 'once' ? 'Дата оплаты' : 'Ближайшая дата оплаты'} type="date" min={today} required {...register('next_due_date')} error={errors.next_due_date?.message} />
    <p className={styles.note}>Название, сумма и валюта изменятся у неоплаченных периодов с сегодняшнего дня. При смене даты или периодичности неоплаченные будущие периоды пересоздаются. Оплаченные периоды не меняются.</p>
    <AssigneesPicker users={users} value={assignees} onChange={setAssignees} disabled={isSubmitting} loading={usersLoading} loadError={usersError} />
    {submitError && <p className={styles.error} role="alert">{submitError}</p>}
    <div className={styles.actions}><Button type="submit" pending={isSubmitting}>Сохранить</Button><Button type="button" variant="secondary" onClick={() => navigate('/recurring-payments')}>Отмена</Button></div>
  </form>
}
