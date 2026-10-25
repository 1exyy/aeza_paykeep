import styles from './States.module.css'

export function EmptyState({ title, description }: { title: string; description: string }) {
  return <section className={styles.card}><h2>{title}</h2><p>{description}</p></section>
}
