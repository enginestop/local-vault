import { useState } from 'react'
import { ArchiveRestore, Check, DatabaseBackup, Download, RotateCcw, Upload } from 'lucide-react'
import { api, saveBlob, type BackupItem } from '../api'
import { errorText } from '../utils/helpers'
import { IconButton } from '../components/IconButton'

export function BackupView({ backups, setBackups, announce, t, onRestored }: { backups: BackupItem[]; setBackups: (items: BackupItem[]) => void; announce: (value: string) => void; t: (key: any) => string; onRestored: () => void }) {
  const [file, setFile] = useState<File | null>(null)
  const [key, setKey] = useState('')
  const [busy, setBusy] = useState(false)
  
  async function refresh(): Promise<void> { setBackups((await api.backups()).items) }
  
  async function manual(): Promise<void> { 
    setBusy(true); 
    try { 
      await api.manualBackup(); 
      await refresh(); 
      announce(t('backupCreated')) 
    } catch (error) { announce(errorText(error)) } finally { setBusy(false) } 
  }
  
  async function download(item: BackupItem): Promise<void> { 
    try { saveBlob(await api.downloadBackup(item.backup_id)) } catch (error) { announce(errorText(error)) } 
  }
  
  async function restore(input: { backupId?: string; file?: File }): Promise<void> { 
    if (!confirm(t('restoreWarning'))) return; setBusy(true); 
    try { 
      await api.restoreBackup({ ...input, masterPassword: key || undefined, recoveryKey: key || undefined }); 
      onRestored() 
    } catch (error) { announce(errorText(error)) } finally { setBusy(false) } 
  }
  
  return (
    <div className="single-page">
      <div className="page-heading backup-heading">
        <div><h1>{t('backupRestore')}</h1></div>
        <button className="primary" disabled={busy} onClick={() => void manual()}><DatabaseBackup size={17} />{t('createBackup')}</button>
      </div>
      <section className="card backups-card">
        <div className="backup-list">
          {backups.map((item) => (
            <div className="backup-row" key={item.backup_id}>
              <ArchiveRestore />
              <div><strong>r{item.vault_revision}</strong><span>{item.kind}</span></div>
              <span className="backup-type">{item.kind}</span>
              <div className="backup-info"><span>{item.created_at}</span></div>
              <span className="valid"><Check size={13} />{item.valid ? t('valid') : t('invalid')}</span>
              <IconButton label={t('download')} onClick={() => void download(item)}><Download size={17} /></IconButton>
              <IconButton label={t('restore')} onClick={() => void restore({ backupId: item.backup_id })}><RotateCcw size={17} /></IconButton>
            </div>
          ))}
        </div>
      </section>
      <aside className="card restore-card">
        <Upload /><h2>{t('restoreFromFile')}</h2>
        <input type="file" accept=".lvbak" onChange={(event) => setFile(event.target.files?.[0] || null)} />
        <input type="password" placeholder={t('historicalKeyOptional')} value={key} onChange={(event) => setKey(event.target.value)} />
        <button className="secondary wide" disabled={!file || busy} onClick={() => file && void restore({ file })}>{t('restore')}</button>
      </aside>
    </div>
  )
}
