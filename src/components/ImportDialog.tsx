import { useState } from 'react'
import { Upload } from 'lucide-react'
import { api, saveBlob, type ImportPreview } from '../api'
import { errorText } from '../utils/helpers'
import { NativeDialog } from './NativeDialog'
import { Dropdown } from './Dropdown'

export function ImportDialog({ t, close, announce, saved, onComplete }: { t: (key: any) => string; close: () => void; announce: (value: string) => void; saved: () => Promise<void>; onComplete: (message: string) => void }) {
  const [file, setFile] = useState<File | null>(null)
  const [profile, setProfile] = useState('auto')
  const [delimiter, setDelimiter] = useState('')
  const [preview, setPreview] = useState<ImportPreview | null>(null)
  const [mapping, setMapping] = useState<Record<string, unknown>>({})
  const [resolutions, setResolutions] = useState<Record<number, string>>({})
  const [busy, setBusy] = useState(false)
  const [confirmOpen, setConfirmOpen] = useState(false)
  
  async function create(): Promise<void> { 
    if (!file) return; setBusy(true); 
    try { 
      const result = await api.importPreview(file, profile, delimiter || null); 
      setPreview(result); 
      setMapping(result.mapping); 
      setResolutions(Object.fromEntries(result.sample.map((row) => [row.row_number, row.resolution]))) 
    } catch (error) { announce(errorText(error)) } finally { setBusy(false) } 
  }
  
  const importChanges = () => ({ mapping, resolutions: Object.entries(resolutions).map(([row_number, resolution]) => ({ row_number: Number(row_number), resolution })) })
  
  async function update(): Promise<void> { 
    if (!preview) return; setBusy(true); 
    try { setPreview(await api.updateImport(preview.id, importChanges())) } catch (error) { announce(errorText(error)) } finally { setBusy(false) } 
  }
  
  async function commit(): Promise<void> {
    if (!preview) return
    setConfirmOpen(true)
  }

  async function confirmCommit(): Promise<void> {
    if (!preview) return
    setConfirmOpen(false)
    setBusy(true)
    try { 
      const refreshed = await api.updateImport(preview.id, importChanges()); 
      setPreview(refreshed); 
      const result = await api.commitImport(preview.id); 
      await saved(); 
      onComplete(t('importedCount').replace('{count}', String(result.committed)))
      close() 
    } catch (error) { announce(errorText(error)) } finally { setBusy(false) } 
  }
  
  return <>
    {!confirmOpen && <NativeDialog title={t('import')} close={close} busy={busy}>
      <div className="modal-form">
        {!preview ? (
          <>
            <div className="drop-zone">
              <Upload size={25} />
              <strong>{t('dropCsv')}</strong>
              <input type="file" accept=".csv,text/csv" onChange={(event) => setFile(event.target.files?.[0] || null)} />
            </div>
            <div className="form-row">
              <label>{t('preset')}<Dropdown value={profile} options={[{ value: 'auto', label: t('autoDetect') }, { value: 'generic', label: 'Generic' }, { value: 'chromium', label: 'Chromium' }, { value: 'firefox', label: 'Firefox' }, { value: 'localvault', label: 'LocalVault' }]} onChange={setProfile} ariaLabel={t('preset')} /></label>
              <label>{t('delimiter')}<Dropdown value={delimiter} options={[{ value: '', label: t('autoDetect') }, { value: ',', label: t('comma') }, { value: ';', label: t('semicolon') }, { value: '\t', label: t('tab') }]} onChange={setDelimiter} ariaLabel={t('delimiter')} /></label>
            </div>
            <div className="modal-actions">
              <button className="secondary" onClick={close}>{t('cancel')}</button>
              <button className="primary" disabled={!file || busy} onClick={() => void create()}>{t('continue')}</button>
            </div>
          </>
        ) : (
          <>
            <p>{t('valid')}: {preview.valid_count} · {t('invalid')}: {preview.invalid_count} · {t('conflicts')}: {preview.conflict_count}</p>
            {preview.warnings.map((warning) => <p className="form-warning" key={warning}>{warning}</p>)}
            <div className="mapping-grid">
              {preview.source_columns.map((column) => (
                <label key={column}>{column}
                  <Dropdown value={String(mapping[column] || 'ignore')} options={['ignore', 'name', 'url', 'username', 'password', 'category', 'tags', 'favorite', 'notes', 'created_at', 'updated_at', 'custom_fields_json'].map((target) => ({ value: target, label: target }))} onChange={(value) => setMapping({ ...mapping, [column]: value })} ariaLabel={column} />
                </label>
              ))}
            </div>
            {preview.sample.filter((row) => row.conflict).map((row) => (
              <label key={row.row_number}>{row.data.name || `#${row.row_number}`}
                <Dropdown value={resolutions[row.row_number] || 'skip'} options={[{ value: 'skip', label: 'Skip' }, { value: 'update', label: 'Update' }, { value: 'keep_both', label: 'Keep both' }]} onChange={(value) => setResolutions({ ...resolutions, [row.row_number]: value })} ariaLabel={String(row.row_number)} />
              </label>
            ))}
            {preview.invalid_count > 0 && <p>{t('invalidRowsAvailable')} <button className="link-button" onClick={async () => { try { saveBlob(await api.downloadImportErrors(preview.id)) } catch (error) { announce(errorText(error)) } }}>{t('download')}</button></p>}
            <div className="modal-actions">
              <button className="secondary" onClick={close}>{t('cancel')}</button>
              <button className="secondary" onClick={() => void update()}>{t('refreshPreview')}</button>
              <button className="primary" disabled={busy} onClick={() => void commit()}>{t('import')}</button>
            </div>
          </>
        )}
      </div>
    </NativeDialog>}
    {confirmOpen && preview && <NativeDialog title={t('import')} close={() => setConfirmOpen(false)}>
      <div className="confirm-dialog-content">
        <p className="eyebrow">LOCALVAULT</p>
        <h2>{t('import')}</h2>
        <p>{t('confirmImport').replace('{count}', String(preview.valid_count))}</p>
        <div className="modal-actions">
          <button type="button" className="secondary" onClick={() => setConfirmOpen(false)}>{t('cancel')}</button>
          <button type="button" className="primary" onClick={() => void confirmCommit()}>{t('import')}</button>
        </div>
      </div>
    </NativeDialog>}
  </>
}
