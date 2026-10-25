import styles from './States.module.css'

export function LoadingState({ label = 'Загружаем…' }: { label?: string }) {
  return <div className={styles.card} role="status"><div className={styles.skeleton} aria-hidden="true" /><span>{label}</span></div>
}
