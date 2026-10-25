import { forwardRef, type ComponentPropsWithRef } from 'react'
import styles from './Button.module.css'

type Props = ComponentPropsWithRef<'button'> & {
  variant?: 'primary' | 'secondary' | 'danger'
  pending?: boolean
}

export const Button = forwardRef<HTMLButtonElement, Props>(function Button(
  { variant = 'primary', pending = false, disabled, children, ...props },
  ref,
) {
  return <button ref={ref} className={styles[variant]} disabled={disabled || pending} aria-busy={pending || undefined} {...props}>{children}</button>
})
