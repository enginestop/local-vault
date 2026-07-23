import { useState, type FormEvent } from 'react'
import { ShieldAlert } from 'lucide-react'
import { api, saveBlob } from '../api'
import { errorText } from '../utils/helpers'
import { NativeDialog } from './NativeDialog'
import { Dropdown } from './Dropdown'

export function ExportDialog({ t, close, announce, filter, selectedIds }: { t: (key: any) => string; close: () => void; announce: (value: string) => void; filter: Record<string, unknown>; selectedIds: string[] }) {
  const [busy, setBusy] = useState(false)
  const [profile, setProfile] = useState('spreadsheet')
  const [scope, setScope] = useState('all')
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
        <label>{t('profile')}<Dropdown name="profile" value={profile} options={[{ value: 'spreadsheet', label: t('spreadsheet') }, { value: 'chromium', label: 'Chromium' }, { value: 'firefox', label: 'Firefox' }]} onChange={setProfile} ariaLabel={t('profile')} /></label>
        <label>{t('scope')}<Dropdown name="scope" value={scope} options={[{ value: 'all', label: t('all') }, { value: 'filtered', label: t('filtered') }, ...(selectedIds.length > 0 ? [{ value: 'selected', label: t('selectedItems') }] : [])]} onChange={setScope} ariaLabel={t('scope')} /></label>
        <label>{t('confirmExport')}<input type="password" name="password" required /></label>
        <div className="modal-actions">
          <button type="button" className="secondary" onClick={close}>{t('cancel')}</button>
          <button className="primary" disabled={busy}>{t('export')}</button>
        </div>
      </form>
    </NativeDialog>
  )
}
