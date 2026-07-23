import { useState, type FormEvent } from 'react'
import { api } from '../api'
import { errorText } from '../utils/helpers'
import { NativeDialog } from './NativeDialog'

export function CategoryDialog({ t, close, announce, saved }: { t: (key: any) => string; close: () => void; announce: (message: string) => void; saved: () => Promise<void> }) {
  const [name, setName] = useState('')
  const [busy, setBusy] = useState(false)

  async function submit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault()
    const value = name.trim()
    if (!value) return
    setBusy(true)
    try {
      await api.createCategory(value)
      await saved()
      announce(t('saved'))
      close()
    } catch (error) {
      announce(errorText(error))
    } finally {
      setBusy(false)
    }
  }

  return <NativeDialog title={t('category')} close={close} busy={busy}>
    <form className="modal-form" onSubmit={(event) => void submit(event)}>
      <label>{t('createCategory')}<input autoFocus value={name} onChange={(event) => setName(event.target.value)} /></label>
      <div className="modal-actions">
        <button type="button" className="secondary" onClick={close} disabled={busy}>{t('cancel')}</button>
        <button className="primary" disabled={busy || !name.trim()}>{t('create')}</button>
      </div>
    </form>
  </NativeDialog>
}
