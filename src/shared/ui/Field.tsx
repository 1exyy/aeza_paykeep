import { useId, type InputHTMLAttributes } from 'react'
import styles from './Field.module.css'

type Props = Omit<InputHTMLAttributes<HTMLInputElement>, 'id'> & {
  label: string
  hint?: string
  error?: string
}

export function Field({ label, hint, error, required, 'aria-describedby': externalDescription, ...inputProps }: Props) {
  const id = useId()
  const hintId = hint ? `${id}-hint` : undefined
  const errorId = error ? `${id}-error` : undefined
  const describedBy = [externalDescription, hintId, errorId].filter(Boolean).join(' ') || undefined

  return <div className={styles.field}>
    <label htmlFor={id}>{label}{required && <span className={styles.required}> *</span>}</label>
    <input {...inputProps} id={id} required={required} aria-invalid={Boolean(error) || undefined} aria-describedby={describedBy} className={styles.input} />
    {hint && <p id={hintId} className={styles.hint}>{hint}</p>}
    {error && <p id={errorId} className={styles.error} role="alert">{error}</p>}
  </div>
}
