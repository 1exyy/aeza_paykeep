import { forwardRef, useId } from 'react'
import * as SelectPrimitive from '@radix-ui/react-select'
import styles from './Select.module.css'

type Option = { value: string; label: string }

type Props = {
  label: string
  value: string
  onValueChange: (value: string) => void
  options: readonly Option[]
  placeholder?: string
  required?: boolean
  disabled?: boolean
  error?: string
}

export const Select = forwardRef<HTMLButtonElement, Props>(function Select({ label, value, onValueChange, options, placeholder, required, disabled, error }, ref) {
  const id = useId()
  const errorId = error ? `${id}-error` : undefined

  return <div className={styles.field}>
    <label htmlFor={id}>{label}{required && <span className={styles.required}> *</span>}</label>
    <SelectPrimitive.Root value={value} onValueChange={onValueChange} disabled={disabled} required={required}>
      <SelectPrimitive.Trigger ref={ref} id={id} className={styles.trigger} aria-invalid={Boolean(error) || undefined} aria-describedby={errorId}>
        <SelectPrimitive.Value placeholder={placeholder} />
        <SelectPrimitive.Icon className={styles.icon} aria-hidden="true"><svg viewBox="0 0 20 20" width="20" height="20" fill="none"><path d="m5 7 5 5 5-5" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" /></svg></SelectPrimitive.Icon>
      </SelectPrimitive.Trigger>
      <SelectPrimitive.Portal>
        <SelectPrimitive.Content className={styles.content} position="popper" sideOffset={6} collisionPadding={{ top: 12, right: 12, bottom: 88, left: 12 }}>
          <SelectPrimitive.ScrollUpButton className={styles.scrollButton} aria-label="Прокрутить вверх"><svg viewBox="0 0 20 20" width="16" height="16" fill="none" aria-hidden="true"><path d="m5 12 5-5 5 5" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" /></svg></SelectPrimitive.ScrollUpButton>
          <SelectPrimitive.Viewport className={styles.viewport}>
            {options.map((option) => <SelectPrimitive.Item key={option.value} value={option.value} className={styles.item}>
              <SelectPrimitive.ItemText>{option.label}</SelectPrimitive.ItemText>
              <SelectPrimitive.ItemIndicator className={styles.indicator} aria-hidden="true">✓</SelectPrimitive.ItemIndicator>
            </SelectPrimitive.Item>)}
          </SelectPrimitive.Viewport>
          <SelectPrimitive.ScrollDownButton className={styles.scrollButton} aria-label="Прокрутить вниз"><svg viewBox="0 0 20 20" width="16" height="16" fill="none" aria-hidden="true"><path d="m5 7 5 5 5-5" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" /></svg></SelectPrimitive.ScrollDownButton>
        </SelectPrimitive.Content>
      </SelectPrimitive.Portal>
    </SelectPrimitive.Root>
    {error && <p id={errorId} className={styles.error} role="alert">{error}</p>}
  </div>
})
