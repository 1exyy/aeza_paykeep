import styles from './States.module.css'

export function AccessDeniedState() {
  return <section className={styles.card} role="alert">
    <h2>Нет доступа</h2>
    <p>У вашей учётной записи нет прав на этот раздел.</p>
  </section>
}
