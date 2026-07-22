import { useState, type FormEvent } from 'react'
import { ShieldAlert } from 'lucide-react'
import { api, saveBlob } from '../api'
import { errorText } from '../utils/helpers'
import { NativeDialog } from './NativeDialog'

export function ExportDialog({ t, close, announce, filter, selectedIds }: { t: (key: any) => string; close: () => void; announce: (value: string) => void; filter: Record<string, unknown>; selectedIds: string[] }) {
  const [busy, setBusy] = useState(false)
  async function submit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault(); setBusy(true)
    const data = new FormData(event.currentTarget)
    try { 
      const scope = String(data.get('scope')); 
      const result = await api.exportVault({ master_password: data.get('password'), profile: data.get('profile'), scope, filter, selected_ids: scope === 'selected' ? selectedIds : [] }); 
      saveBlob(result); 
      announce(t('exportSuccess')); 
      close() 
    } catch (error) { announce(errorText(error)) } finally { setBusy(false) }
  }
  return (
    <NativeDialog title={t('export')} close={close} busy={busy}>
      <form className="modal-form" onSubmit={(event) => void submit(event)}>
        <div className="plaintext-warning"><ShieldAlert size={18} /><div><strong>{t('plaintextWarning')}</strong><span>{t('plaintextDetail')}</span></div></div>
        <label>{t('profile')}<select name="profile"><option value="spreadsheet">{t('spreadsheet')}</option><option value="chromium">Chromium</option><option value="firefox">Firefox</option></select></label>
        <label>{t('scope')}<select name="scope"><option value="all">{t('all')}</option><option value="filtered">{t('filtered')}</option>{selectedIds.length > 0 && <option value="selected">{t('selectedItems')}</option>}</select></label>
        <label>{t('confirmExport')}<input type="password" name="password" required /></label>
        <div className="modal-actions">
          <button type="button" className="secondary" onClick={close}>{t('cancel')}</button>
          <button className="primary" disabled={busy}>{t('export')}</button>
        </div>
      </form>
    </NativeDialog>
  )
}
