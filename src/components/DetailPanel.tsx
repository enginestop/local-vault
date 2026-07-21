import { useState } from 'react'
import { Copy, ExternalLink, Eye, EyeOff, History, SlidersHorizontal, Sparkles, Trash2, X } from 'lucide-react'
import { api, type Category, type Credential, type Lang } from '../api'
import { colorFor, errorText, initials, relativeTime } from '../utils/helpers'
import { Field } from './Field'
import { IconButton } from './IconButton'

export function DetailPanel({ item, categories, lang, t, close, announce, reload, edit, generator }: { item: Credential; categories: Category[]; lang: Lang; t: (key: any) => string; close: () => void; announce: (value: string) => void; reload: () => Promise<void>; edit: () => void; generator: () => void }) {
  const [revealed, setRevealed] = useState(false)
  const [historyOpen, setHistoryOpen] = useState(false)
  
  async function copy(label: string, value: string): Promise<void> { 
    try { 
      await navigator.clipboard.writeText(value); 
      announce(`${label} ${t('copiedClipboard')}`) 
    } catch { 
      announce(t('clipboardBlocked')) 
    } 
  }
  
  function openUrl(): void {
    if (!item.url) return
    let parsed: URL
    try { parsed = new URL(item.url) } catch { announce(t('invalidUrl')); return }
    if (!['http:', 'https:'].includes(parsed.protocol)) { announce(t('unsupportedUrlScheme')); return }
    if (confirm(`${t('openExternalUrl')}\n${parsed.toString()}`)) window.open(parsed.toString(), '_blank', 'noopener,noreferrer')
  }
  
  async function remove(): Promise<void> {
    if (!confirm(`${t('confirmAction')} ${item.name}?`)) return
    try { 
      if (item.deleted_at) await api.purgeCredential(item.id, item.revision); 
      else await api.trashCredential(item.id, item.revision); 
      await reload(); 
      close() 
    } catch (error) { announce(errorText(error)) }
  }
  
  return (
    <aside className="detail-panel" aria-label={`${t('detail')} ${item.name}`}>
      <div className="detail-top">
        <span>{t('detail')}</span>
        <IconButton label={t('close')} onClick={close}><X size={19} /></IconButton>
      </div>
      <div className="detail-scroll">
        <div className="detail-identity">
          <span className="avatar avatar-lg" style={{ background: colorFor(item.id) }}>{initials(item.name)}</span>
          <div>
            <h2>{item.name}</h2>
            {item.url && <button className="link-button" onClick={openUrl}>{item.url} <ExternalLink size={13} /></button>}
          </div>
        </div>
        <div className="detail-section">
          <Field label={t('username')} value={item.username || ''} action={<IconButton label={`${t('copy')} ${t('username')}`} onClick={() => void copy(t('username'), item.username || '')}><Copy size={16} /></IconButton>} />
          <Field label={t('password')} value={revealed ? item.password : '••••••••••••'} action={<><IconButton label={t('reveal')} onClick={() => setRevealed(!revealed)}>{revealed ? <EyeOff size={16} /> : <Eye size={16} />}</IconButton><IconButton label={`${t('copy')} ${t('password')}`} onClick={() => void copy(t('password'), item.password)}><Copy size={16} /></IconButton></>} />
          <button className="generate-link" onClick={generator}><Sparkles size={15} /> {t('generateNew')}</button>
        </div>
        <div className="detail-section">
          <p>{item.notes || t('noNotes')}</p>
        </div>
        <div className="detail-section">
          <button className="history-button" onClick={() => setHistoryOpen(!historyOpen)}><History size={16} /><span>{t('history')} ({item.password_history.length})</span></button>
          {historyOpen && item.password_history.map((entry) => <Field key={entry.id} label={relativeTime(entry.changed_at, lang)} value="••••••••" action={<IconButton label={`${t('copy')} ${t('password')}`} onClick={() => void copy(t('password'), entry.password)}><Copy size={16} /></IconButton>} />)}
        </div>
      </div>
      <div className="detail-actions">
        <button className="secondary grow" onClick={edit}><SlidersHorizontal size={16} /> {t('edit')}</button>
        <button className="danger-icon" onClick={() => void remove()}><Trash2 size={17} /></button>
      </div>
    </aside>
  )
}
