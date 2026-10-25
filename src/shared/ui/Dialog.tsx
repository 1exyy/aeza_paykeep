import type { ReactElement, ReactNode } from 'react'
import * as DialogPrimitive from '@radix-ui/react-dialog'
import { Button } from './Button'
import styles from './Dialog.module.css'

type Props = {
  trigger: ReactElement
  title: string
  description: string
  children?: ReactNode
  open?: boolean
  onOpenChange?: (open: boolean) => void
  closeLabel?: string
  cancelFirst?: boolean
}

export function Dialog({ trigger, title, description, children, open, onOpenChange, closeLabel = 'Закрыть', cancelFirst = false }: Props) {
  const close = <div className={styles.actions}><DialogPrimitive.Close asChild><Button variant="secondary">{closeLabel}</Button></DialogPrimitive.Close></div>
  return <DialogPrimitive.Root open={open} onOpenChange={onOpenChange}>
    <DialogPrimitive.Trigger asChild>{trigger}</DialogPrimitive.Trigger>
    <DialogPrimitive.Portal>
      <DialogPrimitive.Overlay className={styles.overlay} />
      <DialogPrimitive.Content className={styles.content}>
        <DialogPrimitive.Title className={styles.title}>{title}</DialogPrimitive.Title>
        <DialogPrimitive.Description className={styles.description}>{description}</DialogPrimitive.Description>
        {cancelFirst && close}
        {children}
        {!cancelFirst && close}
      </DialogPrimitive.Content>
    </DialogPrimitive.Portal>
  </DialogPrimitive.Root>
}
