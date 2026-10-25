import { useState, type FormEvent } from 'react'
import { useOutletContext } from 'react-router'
import type { SessionContext } from '@/app/SessionGate'
import { useAddAttachmentLinkMutation, useDeleteAttachmentMutation, useDownloadAttachmentFileMutation, useGetAttachmentsQuery, useUploadAttachmentFileMutation, type Attachment } from '@/entities/attachment'
import { getHttpStatus, getSafeErrorMessage } from '@/shared/api'
import { openExternalLink } from '@/shared/lib/telegram'
import { Button, EmptyState, ErrorState, Field, LoadingState } from '@/shared/ui'
import styles from './AttachmentsPanel.module.css'

const maxFileBytes = 10 * 1024 * 1024
const allowedTypes = new Set(['image/jpeg', 'image/png', 'application/pdf'])

function validLink(value: string): boolean {
  try {
    const url = new URL(value)
    return (url.protocol === 'https:' || url.protocol === 'http:') && value.length <= 2048
  } catch {
    return false
  }
}

export function AttachmentsPanel({ occurrenceId }: { occurrenceId: number }) {
  const { user } = useOutletContext<SessionContext>()
  const { data: attachments, error, isLoading, isFetching, refetch } = useGetAttachmentsQuery(occurrenceId)
  const [addLink, { isLoading: isAddingLink }] = useAddAttachmentLinkMutation()
  const [uploadFile, { isLoading: isUploading }] = useUploadAttachmentFileMutation()
  const [downloadFile, { isLoading: isDownloading, reset: resetDownload }] = useDownloadAttachmentFileMutation()
  const [deleteAttachment, { isLoading: isDeleting }] = useDeleteAttachmentMutation()
  const [url, setUrl] = useState('')
  const [title, setTitle] = useState('')
  const [file, setFile] = useState<File | null>(null)
  const [message, setMessage] = useState<string>()
  const [notice, setNotice] = useState<string>()
  const pending = isAddingLink || isUploading || isDownloading || isDeleting
  const limitReached = (attachments?.length ?? 0) >= 5

  async function submitLink(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setMessage(undefined)
    setNotice(undefined)
    if (!validLink(url)) return setMessage('Введите полный адрес http:// или https:// длиной до 2048 символов.')
    if (title.length > 100) return setMessage('Название ссылки — не более 100 символов.')
    try {
      await addLink({ occurrenceId, url, title: title.trim() || null }).unwrap()
      setUrl('')
      setTitle('')
      setNotice('Ссылка добавлена.')
    } catch (requestError) {
      setMessage(getSafeErrorMessage(requestError, 'Не удалось добавить ссылку. Проверьте данные и попробуйте ещё раз.'))
    }
  }

  async function submitFile(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const input = event.currentTarget.elements.namedItem('receipt')
    setMessage(undefined)
    setNotice(undefined)
    if (!file) return setMessage('Выберите файл.')
    if (!allowedTypes.has(file.type)) return setMessage('Можно загрузить JPEG, PNG или PDF.')
    if (file.size > maxFileBytes) return setMessage('Файл должен быть не больше 10 МБ.')
    try {
      await uploadFile({ occurrenceId, file }).unwrap()
      setFile(null)
      if (input instanceof HTMLInputElement) input.value = ''
      setNotice('Файл добавлен.')
    } catch (requestError) {
      setMessage(getSafeErrorMessage(requestError, 'Не удалось загрузить файл. Попробуйте ещё раз.'))
    }
  }

  async function download(item: Attachment) {
    setMessage(undefined)
    setNotice(undefined)
    try {
      const objectUrl = await downloadFile(item.id).unwrap()
      const anchor = document.createElement('a')
      anchor.href = objectUrl
      anchor.download = item.file_name || 'чек'
      document.body.append(anchor)
      anchor.click()
      anchor.remove()
      resetDownload()
      window.setTimeout(() => URL.revokeObjectURL(objectUrl), 60_000)
    } catch (requestError) {
      setMessage(getSafeErrorMessage(requestError, 'Не удалось скачать файл. Попробуйте ещё раз.'))
    }
  }

  async function remove(item: Attachment) {
    if (!window.confirm('Удалить вложение?')) return
    setMessage(undefined)
    setNotice(undefined)
    try {
      await deleteAttachment({ id: item.id, occurrenceId }).unwrap()
      setNotice('Вложение удалено.')
    } catch (requestError) {
      setMessage(getSafeErrorMessage(requestError, 'Не удалось удалить вложение. Попробуйте ещё раз.'))
    }
  }

  return <section className={styles.panel} aria-labelledby="attachments-title">
    <h2 id="attachments-title">Чеки и ссылки</h2>
    {isLoading && <LoadingState />}
    {error && <ErrorState title={getHttpStatus(error) === 403 ? 'Нет доступа к вложениям' : 'Не удалось загрузить вложения'} onRetry={() => void refetch()} />}
    {attachments && <>
      {isFetching && <p role="status">Обновляем вложения…</p>}
      {attachments.length === 0 && <EmptyState title="Вложений пока нет" description="К этому периоду ещё не добавили чек или ссылку." />}
      {attachments.length > 0 && <ul className={styles.list}>{attachments.map((item) => <li key={item.id}>
        <div className={styles.itemText}><strong>{item.title || item.file_name || 'Ссылка'}</strong><span>{item.kind === 'file' ? 'Файл' : 'Ссылка'} · добавил {item.created_by.login}</span></div>
        <div className={styles.actions}>
          {item.kind === 'file' && <Button variant="secondary" disabled={pending} onClick={() => void download(item)}>Скачать</Button>}
          {item.kind === 'link' && <Button variant="secondary" disabled={pending} onClick={() => {
            if (!item.url || !openExternalLink(item.url)) setMessage('Не удалось открыть ссылку: допустимы только http:// и https://.')
          }}>Открыть</Button>}
          {(user.role === 'admin' || user.id === item.created_by.id) && <Button variant="danger" disabled={pending} onClick={() => void remove(item)}>Удалить</Button>}
        </div>
      </li>)}</ul>}
      {limitReached ? <p>На один платёж можно добавить не больше пяти вложений.</p> : <div className={styles.forms}>
        <form onSubmit={(event) => void submitLink(event)}>
          <h3>Добавить ссылку</h3>
          <Field label="Адрес ссылки" type="url" value={url} onChange={(event) => setUrl(event.target.value)} maxLength={2048} required />
          <Field label="Название ссылки" value={title} onChange={(event) => setTitle(event.target.value)} maxLength={100} />
          <Button type="submit" pending={isAddingLink} disabled={pending}>Добавить ссылку</Button>
        </form>
        <form onSubmit={(event) => void submitFile(event)}>
          <h3>Добавить файл</h3>
          <label className={styles.fileLabel} htmlFor="receipt-file">Чек: JPEG, PNG или PDF, до 10 МБ</label>
          <input id="receipt-file" name="receipt" type="file" accept="image/jpeg,image/png,application/pdf" onChange={(event) => setFile(event.target.files?.[0] ?? null)} />
          <Button type="submit" pending={isUploading} disabled={pending}>Загрузить файл</Button>
        </form>
      </div>}
    </>}
    {message && <p role="alert" className={styles.error}>{message}</p>}
    {notice && <p role="status">{notice}</p>}
  </section>
}
