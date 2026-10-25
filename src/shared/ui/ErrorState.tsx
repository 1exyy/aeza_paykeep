import { Button } from './Button'
import styles from './States.module.css'

export function ErrorState({ title, onRetry }: { title: string; onRetry?: () => void }) {
  return <section className={styles.card} role="alert"><h2>{title}</h2>{onRetry && <Button variant="secondary" onClick={onRetry}>Повторить</Button>}</section>
}
