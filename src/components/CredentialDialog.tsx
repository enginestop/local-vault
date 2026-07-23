import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { Clipboard, Sparkles } from 'lucide-react'
import { api, type Category, type Credential } from '../api'
import { Dropdown } from './Dropdown'
import { errorText } from '../utils/helpers'
import { NativeDialog } from './NativeDialog'
import { IconButton } from './IconButton'

export function CredentialDialog({ credential, startGenerator, categories, t, announce, close, saved }: { credential: Credential | null; startGenerator: boolean; categories: Category[]; t: (key: any) => string; announce: (value: string) => void; close: () => void; saved: () => Promise<void> }) {
  const [name, setName] = useState(credential?.name || '')
  const [username, setUsername] = useState(credential?.username || '')
  const [url, setUrl] = useState(credential?.url || '')
  const [password, setPassword] = useState(credential?.password || '')
  const [notes, setNotes] = useState(credential?.notes || '')
  const [tagValue, setTagValue] = useState((credential?.tags || []).join(', '))
  const [category, setCategory] = useState(credential?.category_id || '')
  const [generator, setGenerator] = useState(startGenerator)
  const [generated, setGenerated] = useState('')
  const [length, setLength] = useState(20)
  const [sets, setSets] = useState({ lower: true, upper: true, digits: true, symbols: true, ambiguous: false })
  const [busy, setBusy] = useState(false)
  
  const generate = useCallback(async () => { 
    try { 
      const result = await api.generate({ length, include_lowercase: sets.lower, include_uppercase: sets.upper, include_digits: sets.digits, include_symbols: sets.symbols, exclude_ambiguous: sets.ambiguous }); 
      setGenerated(result.password) 
    } catch (error) { announce(errorText(error)) } 
  }, [announce, length, sets])
  
  useEffect(() => { if (generator) void generate() }, [generator, generate])
  
  async function submit(event: FormEvent): Promise<void> {
    event.preventDefault(); setBusy(true)
    try { 
      const body = { name, username: username || null, url: url || null, password, notes, tags: tagValue.split(',').map((tag) => tag.trim()).filter(Boolean), category_id: category || null }; 
      if (credential) await api.updateCredential(credential.id, body, credential.revision); 
      else await api.createCredential(body); 
      await saved(); 
      announce(t('saved')); 
      close() 
    } catch (error) { announce(errorText(error)) } finally { setBusy(false) }
  }
  
  return (
    <NativeDialog title={generator ? t('generator') : credential ? t('edit') : t('newCredential')} close={close} busy={busy}>
      {generator ? (
        <div className="generator-content">
          <div className="generated-box">
            <span>{generated || '—'}</span>
            <IconButton label={t('copy')} onClick={() => void navigator.clipboard.writeText(generated)}><Clipboard size={17} /></IconButton>
          </div>
          <label className="range-label">{t('length')} {length}<input type="range" min="4" max="256" value={length} onChange={(event) => setLength(Number(event.target.value))} /></label>
          <div className="charset-grid">
            {(['lower', 'upper', 'digits', 'symbols'] as const).map((key) => <label key={key}><input type="checkbox" checked={sets[key]} onChange={(event) => setSets({ ...sets, [key]: event.target.checked })} />{t(key)}</label>)}
            <label><input type="checkbox" checked={sets.ambiguous} onChange={(event) => setSets({ ...sets, ambiguous: event.target.checked })} />{t('excludeAmbiguous')}</label>
          </div>
          <div className="modal-actions">
            <button className="secondary" onClick={() => void generate()}>{t('regenerate')}</button>
            <button className="primary" disabled={!generated} onClick={() => { setPassword(generated); setGenerator(false) }}>{t('usePassword')}</button>
          </div>
        </div>
      ) : (
        <form className="modal-form" onSubmit={(event) => void submit(event)}>
          <label>{t('name')}<input autoFocus required value={name} onChange={(event) => setName(event.target.value)} /></label>
          <div className="form-row">
            <label>{t('username')}<input value={username} onChange={(event) => setUsername(event.target.value)} /></label>
            <label>{t('category')}<Dropdown value={category} options={[{ value: '', label: '—' }, ...categories.map((item) => ({ value: item.id, label: item.name }))]} onChange={setCategory} ariaLabel={t('category')} /></label>
          </div>
          <label>URL<input value={url} onChange={(event) => setUrl(event.target.value)} /></label>
          <label>{t('password')}
            <div className="input-with-action">
              <input type="password" value={password} onChange={(event) => setPassword(event.target.value)} />
              <button type="button" onClick={() => setGenerator(true)}><Sparkles size={15} />{t('generateNew')}</button>
            </div>
          </label>
          <label>{t('tags')}<input value={tagValue} onChange={(event) => setTagValue(event.target.value)} /></label>
          <label>{t('notes')}<textarea rows={3} value={notes} onChange={(event) => setNotes(event.target.value)} /></label>
          <div className="modal-actions">
            <button type="button" className="secondary" onClick={close}>{t('cancel')}</button>
            <button className="primary" disabled={busy}>{t('save')}</button>
          </div>
        </form>
      )}
    </NativeDialog>
  )
}
