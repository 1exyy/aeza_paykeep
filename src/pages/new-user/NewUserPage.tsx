import { Link } from 'react-router'
import { CreateUserForm } from '@/features/manage-user'
import styles from './NewUserPage.module.css'

export function NewUserPage() {
  return <main className={styles.page}>
    <Link to="/users">К пользователям</Link>
    <h1>Новый пользователь</h1>
    <CreateUserForm />
  </main>
}
