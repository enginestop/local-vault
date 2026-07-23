import { useCallback, useEffect, useState } from 'react'
import { ShieldAlert } from 'lucide-react'
import { api, setToken, type Category, type Lang, type SecurityStatus, type VaultSettings } from '../api'
import { errorText, strengthOf } from '../utils/helpers'

export function SettingsView({ lang, settings, categories, tags, vaultRevision, t, announce, reload, setLang, showRecovery, navigateBackup }: { lang: Lang; settings: VaultSettings | null; categories: Category[]; tags: string[]; vaultRevision: number; t: (key: any) => string; announce: (value: string) => void; reload: () => Promise<void>; setLang: (lang: Lang) => void; showRecovery: (key: string, after?: () => void) => void; navigateBackup: () => void }) {
  const [section, setSection] = useState<'general' | 'security' | 'master' | 'host' | 'backup'>('general')
  const [security, setSecurity] = useState<SecurityStatus | null>(null)
  const [host, setHost] = useState<{ port: number; autostart: boolean } | null>(null)
  const [loadError, setLoadError] = useState('')
  const [tagMode, setTagMode] = useState(settings?.tag_filter_mode || 'and')
  const [pageSize, setPageSize] = useState(settings?.page_size || 50)
  const [draftLang, setDraftLang] = useState(lang)
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const [confirmNext, setConfirmNext] = useState('')
  const [weakAck, setWeakAck] = useState(false)
  const [resetPhrase, setResetPhrase] = useState('')
  const [busy, setBusy] = useState(false)
  
  const load = useCallback(async () => { 
    setLoadError(''); 
    try { 
      const [sec, hostResult] = await Promise.all([api.security(), api.host()]); 
      setSecurity(sec); 
      setHost({ port: hostResult.port, autostart: hostResult.autostart }) 
    } catch (error) { setLoadError(errorText(error)) } 
  }, [])
  
  useEffect(() => { void load() }, [load])
  
  useEffect(() => { 
    if (settings) { setTagMode(settings.tag_filter_mode); setPageSize(settings.page_size); setDraftLang(settings.language) } 
  }, [settings])
  
  async function saveGeneral(): Promise<void> { 
    setBusy(true); 
    try { 
      await api.updateGeneral({ language: draftLang, tag_filter_mode: tagMode, page_size: pageSize }); 
      setLang(draftLang); 
      localStorage.setItem('lv_lang', draftLang); 
      await reload(); 
      announce(t('saved')) 
    } catch (error) { announce(errorText(error)) } finally { setBusy(false) } 
  }
  
  async function changeMaster(): Promise<void> { 
    setBusy(true); 
    try { 
      await api.changeMaster({ current_master_password: current, new_master_password: next, confirm_new_master_password: confirmNext, weak_password_acknowledged: weakAck }); 
      announce(t('masterChanged')); 
      setCurrent(''); setNext(''); setConfirmNext('') 
    } catch (error) { announce(errorText(error)) } finally { setBusy(false) } 
  }
  
  async function recoveryAction(action: 'enable' | 'rotate'): Promise<void> {
    setBusy(true); 
    try { 
      const result = await api.recoveryAction(action, current);
      if (result.recovery_key) showRecovery(result.recovery_key); 
      await load() 
    } catch (error) { announce(errorText(error)) } finally { setBusy(false) } 
  }

  async function disableRecovery(): Promise<void> {
    if (!confirm(t('confirmDisableRecovery'))) return
    setBusy(true)
    try { await api.disableRecovery(current); await load() }
    catch (error) { announce(errorText(error)) }
    finally { setBusy(false) }
  }
  
  async function reset(): Promise<void> { 
    if (resetPhrase !== 'RESET LOCALVAULT' || !confirm(t('confirmReset'))) return; 
    setBusy(true); 
    try { 
      const result = await api.resetVault({ master_password: current, confirm_recovery_phrase: resetPhrase, new_master_password: next, confirm_new_master_password: confirmNext, weak_password_acknowledged: weakAck, create_recovery_key: true }); 
      if (result.recovery_key) showRecovery(result.recovery_key, () => { setToken(null); location.reload() }); 
      else { setToken(null); location.reload() } 
    } catch (error) { announce(errorText(error)) } finally { setBusy(false) } 
  }
  
  async function saveHost(): Promise<void> { 
    if (!host) return; setBusy(true); 
    try { 
      const result = await api.updateHost(host); 
      announce(result.restart_required ? t('restartRequired') : t('saved')) 
    } catch (error) { announce(errorText(error)) } finally { setBusy(false) } 
  }
  
  async function createCategory(): Promise<void> { 
    const name = prompt(t('createCategory')); 
    if (!name) return; 
    try { await api.createCategory(name); await reload() } catch (error) { announce(errorText(error)) } 
  }
  
  async function renameCategory(category: Category): Promise<void> { 
    if (busy) return; 
    const name = prompt(t('renameCategory'), category.name); 
    if (!name) return; 
    setBusy(true); 
    try { await api.updateCategory(category.id, name, category.revision); await reload() } catch (error) { announce(errorText(error)) } finally { setBusy(false) } 
  }
  
  async function removeCategory(category: Category): Promise<void> { 
    if (busy || !confirm(`${t('confirmAction')} ${category.name}?`)) return; 
    setBusy(true); 
    try { await api.deleteCategory(category.id, category.revision); await reload() } catch (error) { announce(errorText(error)) } finally { setBusy(false) } 
  }
  
  async function renameTag(tag: string): Promise<void> { 
    if (busy) return; 
    const name = prompt(t('renameTag'), tag); 
    if (!name) return; 
    setBusy(true); 
    try { await api.renameTag(tag, name, vaultRevision); await reload() } catch (error) { announce(errorText(error)) } finally { setBusy(false) } 
  }
  
  async function removeTag(tag: string): Promise<void> { 
    if (busy || !confirm(`${t('confirmAction')} ${tag}?`)) return; 
    setBusy(true); 
    try { await api.deleteTag(tag, vaultRevision); await reload() } catch (error) { announce(errorText(error)) } finally { setBusy(false) } 
  }
  
  async function createTag(): Promise<void> { 
    const name = prompt(t('createTag')); 
    if (!name) return; 
    try { await api.createTag(name); await reload() } catch (error) { announce(errorText(error)) } 
  }
  
  return (
    <div className="single-page settings-page">
      <div className="page-heading"><h1>{t('settings')}</h1></div>
      {loadError && <div className="form-error">{loadError}<button onClick={() => void load()}>{t('retry')}</button></div>}
      <div className="settings-layout">
        <nav className="settings-nav">
          {(['general', 'security', 'master', 'host', 'backup'] as const).map((key) => <button key={key} className={section === key ? 'active' : ''} onClick={() => setSection(key)}>{t(key === 'master' ? 'masterRecovery' : key === 'host' ? 'hostNetwork' : key)}</button>)}
        </nav>
        <div className="settings-content">
          {section === 'general' && (
            <section className="card setting-section">
              <div className="card-title"><h2>{t('general')}</h2></div>
              <div className="setting-row"><strong>{t('language')}</strong><select value={draftLang} onChange={(event) => setDraftLang(event.target.value as Lang)}><option value="id">Bahasa Indonesia</option><option value="en">English</option></select></div>
              <div className="setting-row"><strong>{t('tagFilterMode')}</strong><select value={tagMode} onChange={(event) => setTagMode(event.target.value as 'and' | 'or')}><option value="and">AND</option><option value="or">OR</option></select></div>
              <div className="setting-row"><strong>{t('itemsPerPage')}</strong><select value={pageSize} onChange={(event) => setPageSize(Number(event.target.value) as 25 | 50 | 100)}><option>25</option><option>50</option><option>100</option></select></div>
              <div className="setting-row"><div><strong>{t('category')} <button onClick={() => void createCategory()}>{t('create')}</button></strong>{categories.map((category) => <span key={category.id}>{category.name} <button onClick={() => void renameCategory(category)}>{t('rename')}</button> <button onClick={() => void removeCategory(category)}>{t('delete')}</button></span>)}</div></div>
              <div className="setting-row"><div><strong>{t('tags')} <button onClick={() => void createTag()}>{t('create')}</button></strong>{tags.map((tag) => <span key={tag}>{tag} <button onClick={() => void renameTag(tag)}>{t('rename')}</button> <button onClick={() => void removeTag(tag)}>{t('delete')}</button></span>)}</div></div>
              <button className="primary save-settings" disabled={busy} onClick={() => void saveGeneral()}>{t('saveSettings')}</button>
            </section>
          )}
          {section === 'security' && (
            <section className="card setting-section">
              <div className="card-title"><h2>{t('security')}</h2></div>
              {security && <div className="setting-row"><div><strong>{security.kdf_algorithm}</strong><span>m={security.kdf_m_cost_kib}, t={security.kdf_t_cost}, p={security.kdf_parallelism}</span></div><span>{security.recovery_enabled ? t('recoveryEnabled') : t('recoveryDisabled')}</span></div>}
              <div className="plaintext-warning"><ShieldAlert /><div><strong>{t('httpBanner')}</strong><span>{t('noThrottleWarning')}</span></div></div>
            </section>
          )}
          {section === 'master' && (
            <section className="card setting-section">
              <div className="card-title"><h2>{t('masterRecovery')}</h2></div>
              <div className="modal-form">
                <label>{t('currentMaster')}<input type="password" value={current} onChange={(event) => setCurrent(event.target.value)} /></label>
                <label>{t('newMaster')}<input type="password" value={next} onChange={(event) => setNext(event.target.value)} /></label>
                <label>{t('confirmNewMaster')}<input type="password" value={confirmNext} onChange={(event) => setConfirmNext(event.target.value)} /></label>
                {strengthOf(next) === 'weak' && <label><input type="checkbox" checked={weakAck} onChange={(event) => setWeakAck(event.target.checked)} />{t('weakPasswordAck')}</label>}
                <button className="primary" disabled={busy} onClick={() => void changeMaster()}>{t('changeMaster')}</button>
                {security?.recovery_enabled ? (
                  <>
                    <button className="secondary" disabled={busy} onClick={() => void recoveryAction('rotate')}>{t('rotateRecovery')}</button>
                    <button className="danger-outline" disabled={busy} onClick={() => void disableRecovery()}>{t('disableRecovery')}</button>
                  </>
                ) : (
                  <button className="secondary" disabled={busy} onClick={() => void recoveryAction('enable')}>{t('enableRecovery')}</button>
                )}
                <label>{t('resetPhrase')}<input value={resetPhrase} onChange={(event) => setResetPhrase(event.target.value)} /></label>
                <button className="danger-outline" disabled={busy} onClick={() => void reset()}>{t('resetVault')}</button>
              </div>
            </section>
          )}
          {section === 'host' && host && (
            <section className="card setting-section">
              <div className="card-title"><h2>{t('hostNetwork')}</h2></div>
              <div className="setting-row"><strong>{t('port')}</strong><input type="number" min="1024" max="65535" value={host.port} onChange={(event) => setHost({ ...host, port: Number(event.target.value) })} /></div>
              <div className="setting-row"><strong>{t('autostart')}</strong><input type="checkbox" checked={host.autostart} onChange={(event) => setHost({ ...host, autostart: event.target.checked })} /></div>
              <div className="setting-row"><span>0.0.0.0 · {t('lanDefault')}</span></div>
              <button className="primary save-settings" disabled={busy} onClick={() => void saveHost()}>{t('save')}</button>
            </section>
          )}
          {section === 'backup' && (
            <section className="card setting-section">
              <div className="card-title"><h2>{t('backup')}</h2></div>
              <button className="primary" onClick={navigateBackup}>{t('openBackup')}</button>
            </section>
          )}
        </div>
      </div>
    </div>
  )
}
