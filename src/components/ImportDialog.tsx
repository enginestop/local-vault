import { useState } from 'react'
import { Upload } from 'lucide-react'
import { api, saveBlob, type ImportPreview } from '../api'
import { errorText } from '../utils/helpers'
import { NativeDialog } from './NativeDialog'

export function ImportDialog({ t, close, announce, saved }: { t: (key: any) => string; close: () => void; announce: (value: string) => void; saved: () => Promise<void> }) {
  const [file, setFile] = useState<File | null>(null)
  const [profile, setProfile] = useState('auto')
  const [delimiter, setDelimiter] = useState('')
  const [preview, setPreview] = useState<ImportPreview | null>(null)
  const [mapping, setMapping] = useState<Record<string, unknown>>({})
  const [resolutions, setResolutions] = useState<Record<number, string>>({})
  const [busy, setBusy] = useState(false)
  
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
    if (!preview || !confirm(t('confirmImport').replace('{count}', String(preview.valid_count)))) return; setBusy(true); 
    try { 
      const refreshed = await api.updateImport(preview.id, importChanges()); 
      setPreview(refreshed); 
      const result = await api.commitImport(preview.id); 
      await saved(); 
      announce(t('importedCount').replace('{count}', String(result.committed))); 
      close() 
    } catch (error) { announce(errorText(error)) } finally { setBusy(false) } 
  }
  
  return (
    <NativeDialog title={t('import')} close={close} busy={busy}>
      <div className="modal-form">
        {!preview ? (
          <>
            <div className="drop-zone">
              <Upload size={25} />
              <strong>{t('dropCsv')}</strong>
              <input type="file" accept=".csv,text/csv" onChange={(event) => setFile(event.target.files?.[0] || null)} />
            </div>
            <div className="form-row">
              <label>{t('preset')}
                <select value={profile} onChange={(event) => setProfile(event.target.value)}>
                  <option value="auto">{t('autoDetect')}</option>
                  <option value="generic">Generic</option>
                  <option value="chromium">Chromium</option>
                  <option value="firefox">Firefox</option>
                  <option value="localvault">LocalVault</option>
                </select>
              </label>
              <label>{t('delimiter')}
                <select value={delimiter} onChange={(event) => setDelimiter(event.target.value)}>
                  <option value="">{t('autoDetect')}</option>
                  <option value=",">{t('comma')}</option>
                  <option value=";">{t('semicolon')}</option>
                  <option value={'\t'}>{t('tab')}</option>
                </select>
              </label>
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
                  <select value={String(mapping[column] || 'ignore')} onChange={(event) => setMapping({ ...mapping, [column]: event.target.value })}>
                    {['ignore', 'name', 'url', 'username', 'password', 'category', 'tags', 'favorite', 'notes', 'created_at', 'updated_at', 'custom_fields_json'].map((target) => <option key={target} value={target}>{target}</option>)}
                  </select>
                </label>
              ))}
            </div>
            {preview.sample.filter((row) => row.conflict).map((row) => (
              <label key={row.row_number}>{row.data.name || `#${row.row_number}`}
                <select value={resolutions[row.row_number] || 'skip'} onChange={(event) => setResolutions({ ...resolutions, [row.row_number]: event.target.value })}>
                  <option value="skip">Skip</option>
                  <option value="update">Update</option>
                  <option value="keep_both">Keep both</option>
                </select>
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
    </NativeDialog>
  )
}
