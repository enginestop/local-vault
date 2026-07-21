import { useState } from 'react'
import { ShieldAlert, Copy, Download } from 'lucide-react'
import { NativeDialog } from './NativeDialog'
import { IconButton } from './IconButton'
import { saveBlob } from '../api'

export function RecoveryKeyDialog({ recoveryKey, acknowledge, t }: { recoveryKey: string; acknowledge: () => void; t: (key: any) => string }) {
  const [saved, setSaved] = useState(false)
  async function copy(): Promise<void> {
    await navigator.clipboard.writeText(recoveryKey)
  }
  function download(): void {
    saveBlob({ blob: new Blob([`${recoveryKey}\n`], { type: 'text/plain' }), filename: 'localvault-recovery-key.txt' })
  }
  return (
    <NativeDialog title={t('recoveryKey')} closeLabel={t('close')} close={() => {}} busy>
      <div className="modal-form">
        <div className="plaintext-warning"><ShieldAlert size={18} /><div><strong>{t('saveRecoveryNow')}</strong><span>{t('recoveryShownOnce')}</span></div></div>
        <div className="generated-box"><span>{recoveryKey}</span><IconButton label={t('copy')} onClick={() => void copy()}><Copy size={17} /></IconButton></div>
        <div className="modal-actions"><button type="button" className="secondary" onClick={download}><Download size={16} /> {t('download')}</button></div>
        <label className="auth-check"><input type="checkbox" checked={saved} onChange={(event) => setSaved(event.target.checked)} /><span>{t('recoverySavedAck')}</span></label>
        <button className="primary wide" disabled={!saved} onClick={acknowledge}>{t('continue')}</button>
      </div>
    </NativeDialog>
  )
}
