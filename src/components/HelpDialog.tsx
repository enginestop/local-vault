import { ShieldAlert } from 'lucide-react'
import { NativeDialog } from './NativeDialog'

export function HelpDialog({ t, close }: { t: (key: any) => string; close: () => void }) { 
  return (
    <NativeDialog title={t('help')} close={close}>
      <div className="modal-form">
        <div className="plaintext-warning"><ShieldAlert /><div><strong>{t('httpBanner')}</strong><span>{t('threatModel')}</span></div></div>
        <h3>{t('shortcuts')}</h3>
        <p><kbd>/</kbd> {t('focusSearch')}</p>
        <p><kbd>Ctrl/Cmd+N</kbd> {t('newCredential')}</p>
        <p><kbd>Ctrl/Cmd+K</kbd> {t('openHelp')}</p>
        <p><kbd>?</kbd> {t('help')}</p>
        <div className="modal-actions"><button className="primary" onClick={close}>{t('close')}</button></div>
      </div>
    </NativeDialog>
  ) 
}
