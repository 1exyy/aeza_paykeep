import { useState } from 'react'
import { Controller, useForm } from 'react-hook-form'
import { useNavigate } from 'react-router'
import { z } from 'zod'
import { AssigneesPicker, isPeriodicity, parseInterval, periodicityOptions, useCreateRecurringPaymentMutation } from '@/entities/recurring-payment'
import type { AssigneesValue, Periodicity, UserRef } from '@/entities/recurring-payment'
import { getSafeErrorMessage } from '@/shared/api'
import { isDateOnly } from '@/shared/lib/date'
import { Button, Field, Select } from '@/shared/ui'
import styles from './CreateRecurringPaymentForm.module.css'

const moneyPattern = /^\d{1,12}(?:\.\d{1,2})?$/

function formSchema(today: string) {
  return z.object({
    title: z.string().trim().min(1, 'Введите название').max(100, 'Не более 100 символов'),
    amount: z.string().regex(moneyPattern, 'Укажите сумму до двух знаков после точки')
      .refine((value) => !/^0+(?:\.0{1,2})?$/.test(value), 'Сумма должна быть больше нуля'),
    currency: z.enum(['RUB', 'USD', 'EUR'], { error: 'Выберите валюту' }),
    next_due_date: z.string().refine(isDateOnly, 'Укажите дату оплаты')
      .refine((value) => value >= today, 'Дата не может быть раньше сегодняшнего дня'),
  })
}

type Values = { title: string; amount: string; currency: 'RUB' | 'USD' | 'EUR' | ''; next_due_date: string; periodicity: Periodicity; interval_days: string }
const currencyOptions = [{ value: 'RUB', label: 'RUB' }, { value: 'USD', label: 'USD' }, { value: 'EUR', label: 'EUR' }]

type Props = {
  today: string
  /** Users from GET /users that can be made responsible. */
  users: readonly UserRef[]
  usersLoading?: boolean
  usersError?: string
}

export function CreateRecurringPaymentForm({ today, users, usersLoading, usersError }: Props) {
  const navigate = useNavigate()
  const [create] = useCreateRecurringPaymentMutation()
  const [submitError, setSubmitError] = useState<string>()
  const [assignees, setAssignees] = useState<AssigneesValue>({ assign_all: false, assignee_ids: [] })
  const { register, control, handleSubmit, setError, clearErrors, setFocus, watch, formState: { errors, isSubmitting } } = useForm<Values>({
    defaultValues: { title: '', amount: '', currency: '', next_due_date: '', periodicity: 'monthly', interval_days: '' },
  })
  const periodicity = watch('periodicity')

  const submit = handleSubmit(async (values) => {
    setSubmitError(undefined)
    clearErrors()
    const parsed = formSchema(today).safeParse(values)
    if (!parsed.success) {
      const first = parsed.error.issues[0]
      const reported = new Set<string>()
      for (const issue of parsed.error.issues) {
        const field = issue.path[0]
        if ((field === 'title' || field === 'amount' || field === 'currency' || field === 'next_due_date') && !reported.has(field)) {
          setError(field, { message: issue.message })
          reported.add(field)
        }
      }
      if (first?.path[0]) setFocus(first.path[0] as keyof Values)
      return
    }
    const interval = values.periodicity === 'every_n_days' ? parseInterval(values.interval_days) : undefined
    if (typeof interval === 'string') {
      setError('interval_days', { message: interval })
      setFocus('interval_days')
      return
    }
    try {
      await create({
        ...parsed.data,
        periodicity: values.periodicity,
        ...(interval !== undefined ? { interval_days: interval } : {}),
        assign_all: assignees.assign_all,
        assignee_ids: assignees.assign_all ? [] : assignees.assignee_ids,
      }).unwrap()
      navigate('/recurring-payments', { replace: true })
    } catch (requestError) {
      setSubmitError(getSafeErrorMessage(requestError, 'Не удалось добавить платёж. Попробуйте ещё раз.'))
    }
  })

  return <form className={styles.form} onSubmit={submit} noValidate>
    <Field label="Название" required {...register('title')} error={errors.title?.message} />
    <Field label="Сумма" required inputMode="decimal" hint="Например, 1500.00" {...register('amount')} error={errors.amount?.message} />
    <Controller name="currency" control={control} render={({ field }) => <Select label="Валюта" required value={field.value} onValueChange={field.onChange} options={currencyOptions} placeholder="Выберите валюту" error={errors.currency?.message} ref={field.ref} />} />
    <Field label={periodicity === 'once' ? 'Дата оплаты' : 'Ближайшая дата оплаты'} type="date" min={today} required {...register('next_due_date')} error={errors.next_due_date?.message} />
    <Controller name="periodicity" control={control} render={({ field }) => <Select label="Периодичность" required value={field.value} onValueChange={(value) => { if (isPeriodicity(value)) field.onChange(value) }} options={periodicityOptions} ref={field.ref} />} />
    {periodicity === 'every_n_days' && <Field label="Интервал, дней" required inputMode="numeric" hint="От 1 до 365" {...register('interval_days')} error={errors.interval_days?.message} />}
    <AssigneesPicker users={users} value={assignees} onChange={setAssignees} disabled={isSubmitting} loading={usersLoading} loadError={usersError} />
    {submitError && <p className={styles.error} role="alert">{submitError}</p>}
    <div className={styles.actions}><Button type="submit" pending={isSubmitting}>Добавить платёж</Button><Button type="button" variant="secondary" onClick={() => navigate('/recurring-payments')}>Отмена</Button></div>
  </form>
}
