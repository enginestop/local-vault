import { useCallback, useEffect, useState, type ReactNode } from 'react'
import { AlertTriangle, CheckCircle2, DatabaseBackup, Globe2, KeyRound, Pencil, Plus, Settings2, ShieldAlert, ShieldCheck, Trash2 } from 'lucide-react'
import { api, setToken, type Category, type Lang, type SecurityStatus, type VaultSettings } from '../api'
import { errorText, strengthOf } from '../utils/helpers'
import { Dropdown } from '../components/Dropdown'

type Section = 'general' | 'security' | 'master' | 'host' | 'backup'

export function SettingsView({ lang, settings, categories, tags, vaultRevision, t, announce, reload, setLang, showRecovery, navigateBackup }: { lang: Lang; settings: VaultSettings | null; categories: Category[]; tags: string[]; vaultRevision: number; t: (key: any) => string; announce: (value: string) => void; reload: () => Promise<void>; setLang: (lang: Lang) => void; showRecovery: (key: string, after?: () => void) => void; navigateBackup: () => void }) {
  const [section, setSection] = useState<Section>('general')
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
    setLoadError('')
    try {
      const [sec, hostResult] = await Promise.all([api.security(), api.host()])
      setSecurity(sec)
      setHost({ port: hostResult.port, autostart: hostResult.autostart })
    } catch (error) { setLoadError(errorText(error)) }
  }, [])

  useEffect(() => { void load() }, [load])
  useEffect(() => {
    if (settings) { setTagMode(settings.tag_filter_mode); setPageSize(settings.page_size); setDraftLang(settings.language) }
  }, [settings])

  async function saveGeneral(): Promise<void> {
    setBusy(true)
    try {
      await api.updateGeneral({ language: draftLang, tag_filter_mode: tagMode, page_size: pageSize })
      setLang(draftLang); localStorage.setItem('lv_lang', draftLang); await reload(); announce(t('saved'))
    } catch (error) { announce(errorText(error)) } finally { setBusy(false) }
  }
  async function changeMaster(): Promise<void> {
    setBusy(true)
    try {
      await api.changeMaster({ current_master_password: current, new_master_password: next, confirm_new_master_password: confirmNext, weak_password_acknowledged: weakAck })
      announce(t('masterChanged')); setCurrent(''); setNext(''); setConfirmNext('')
    } catch (error) { announce(errorText(error)) } finally { setBusy(false) }
  }
  async function recoveryAction(action: 'enable' | 'rotate'): Promise<void> {
    setBusy(true)
    try { const result = await api.recoveryAction(action, current); if (result.recovery_key) showRecovery(result.recovery_key); await load() }
    catch (error) { announce(errorText(error)) } finally { setBusy(false) }
  }
  async function disableRecovery(): Promise<void> {
    if (!confirm(t('confirmDisableRecovery'))) return
    setBusy(true)
    try { await api.disableRecovery(current); await load() } catch (error) { announce(errorText(error)) } finally { setBusy(false) }
  }
  async function reset(): Promise<void> {
    if (resetPhrase !== 'RESET LOCALVAULT' || !confirm(t('confirmReset'))) return
    setBusy(true)
    try {
      const result = await api.resetVault({ master_password: current, confirm_recovery_phrase: resetPhrase, new_master_password: next, confirm_new_master_password: confirmNext, weak_password_acknowledged: weakAck, create_recovery_key: true })
      if (result.recovery_key) showRecovery(result.recovery_key, () => { setToken(null); location.reload() }); else { setToken(null); location.reload() }
    } catch (error) { announce(errorText(error)) } finally { setBusy(false) }
  }
  async function saveHost(): Promise<void> {
    if (!host) return
    setBusy(true)
    try { const result = await api.updateHost(host); announce(result.restart_required ? t('restartRequired') : t('saved')) }
    catch (error) { announce(errorText(error)) } finally { setBusy(false) }
  }
  async function createCategory(): Promise<void> { const name = prompt(t('createCategory')); if (name) try { await api.createCategory(name); await reload() } catch (error) { announce(errorText(error)) } }
  async function renameCategory(category: Category): Promise<void> { if (busy) return; const name = prompt(t('renameCategory'), category.name); if (!name) return; setBusy(true); try { await api.updateCategory(category.id, name, category.revision); await reload() } catch (error) { announce(errorText(error)) } finally { setBusy(false) } }
  async function removeCategory(category: Category): Promise<void> { if (busy || !confirm(`${t('confirmAction')} ${category.name}?`)) return; setBusy(true); try { await api.deleteCategory(category.id, category.revision); await reload() } catch (error) { announce(errorText(error)) } finally { setBusy(false) } }
  async function renameTag(tag: string): Promise<void> { if (busy) return; const name = prompt(t('renameTag'), tag); if (!name) return; setBusy(true); try { await api.renameTag(tag, name, vaultRevision); await reload() } catch (error) { announce(errorText(error)) } finally { setBusy(false) } }
  async function removeTag(tag: string): Promise<void> { if (busy || !confirm(`${t('confirmAction')} ${tag}?`)) return; setBusy(true); try { await api.deleteTag(tag, vaultRevision); await reload() } catch (error) { announce(errorText(error)) } finally { setBusy(false) } }
  async function createTag(): Promise<void> { const name = prompt(t('createTag')); if (name) try { await api.createTag(name); await reload() } catch (error) { announce(errorText(error)) } }

  const navItems: { key: Section; icon: ReactNode; label: string }[] = [
    { key: 'general', icon: <Settings2 size={17} aria-hidden="true" />, label: t('general') },
    { key: 'security', icon: <ShieldCheck size={17} aria-hidden="true" />, label: t('security') },
    { key: 'master', icon: <KeyRound size={17} aria-hidden="true" />, label: t('masterRecovery') },
    { key: 'host', icon: <Globe2 size={17} aria-hidden="true" />, label: t('hostNetwork') },
    { key: 'backup', icon: <DatabaseBackup size={17} aria-hidden="true" />, label: t('backup') },
  ]
  const descriptions: Record<Section, string> = { general: t('settingsGeneralDescription'), security: t('settingsSecurityDescription'), master: t('settingsMasterDescription'), host: t('settingsHostDescription'), backup: t('settingsBackupDescription') }
  const title = navItems.find((item) => item.key === section)?.label || t('settings')

  return <div className="single-page settings-page">
    <div className="settings-intro"><div><p className="eyebrow">{t('settingsEyebrow')}</p><h1>{t('settings')}</h1><p>{t('settingsDescription')}</p></div></div>
    {loadError && <div className="form-error" role="alert">{loadError}<button type="button" onClick={() => void load()}>{t('retry')}</button></div>}
    <div className="settings-layout">
      <nav className="settings-nav" aria-label={t('settingsNavigation')}>
        {navItems.map((item) => <button type="button" key={item.key} className={section === item.key ? 'active' : ''} aria-current={section === item.key ? 'page' : undefined} onClick={() => setSection(item.key)}>{item.icon}<span>{item.label}</span></button>)}
      </nav>
      <div className="settings-content">
        <div className="settings-section-heading"><div><p className="eyebrow">{t('settingsSection')}</p><h2>{title}</h2><p>{descriptions[section]}</p></div></div>
        {section === 'general' && <section className="card setting-section" aria-labelledby="settings-general-title">
          <div className="card-title"><div><h2 id="settings-general-title">{t('generalPreferences')}</h2><p>{t('generalPreferencesDescription')}</p></div></div>
          <div className="settings-fields">
            <div className="setting-row"><div className="setting-copy"><strong>{t('language')}</strong><span>{t('languageDescription')}</span></div><Dropdown value={draftLang} options={[{ value: 'id', label: 'Bahasa Indonesia' }, { value: 'en', label: 'English' }]} onChange={(value) => setDraftLang(value as Lang)} ariaLabel={t('language')} /></div>
            <div className="setting-row"><div className="setting-copy"><strong>{t('tagFilterMode')}</strong><span>{t('tagFilterModeDescription')}</span></div><Dropdown value={tagMode} options={[{ value: 'and', label: t('and') }, { value: 'or', label: t('or') }]} onChange={(value) => setTagMode(value as 'and' | 'or')} ariaLabel={t('tagFilterMode')} /></div>
            <div className="setting-row"><div className="setting-copy"><strong>{t('itemsPerPage')}</strong><span>{t('itemsPerPageDescription')}</span></div><Dropdown value={String(pageSize)} options={['25', '50', '100'].map((value) => ({ value, label: value }))} onChange={(value) => setPageSize(Number(value) as 25 | 50 | 100)} ariaLabel={t('itemsPerPage')} /></div>
          </div>
          <div className="settings-subsection"><div className="subsection-heading"><div><h3>{t('category')}</h3><p>{t('categoryDescription')}</p></div><button type="button" className="secondary compact-action" onClick={() => void createCategory()}><Plus size={15} />{t('create')}</button></div><div className="settings-list">{categories.length ? categories.map((category) => <div className="settings-list-item" key={category.id}><span className="item-dot" /><strong title={category.name}>{category.name}</strong><div className="item-actions"><button type="button" aria-label={`${t('rename')} ${category.name}`} title={t('rename')} disabled={busy} onClick={() => void renameCategory(category)}><Pencil size={15} /></button><button type="button" className="item-danger" aria-label={`${t('delete')} ${category.name}`} title={t('delete')} disabled={busy} onClick={() => void removeCategory(category)}><Trash2 size={15} /></button></div></div>) : <p className="settings-empty">{t('noCategories')}</p>}</div></div>
          <div className="settings-subsection"><div className="subsection-heading"><div><h3>{t('tags')}</h3><p>{t('tagsDescription')}</p></div><button type="button" className="secondary compact-action" onClick={() => void createTag()}><Plus size={15} />{t('create')}</button></div><div className="settings-list">{tags.length ? tags.map((tag) => <div className="settings-list-item" key={tag}><span className="tag-chip">#</span><strong title={tag}>{tag}</strong><div className="item-actions"><button type="button" aria-label={`${t('rename')} ${tag}`} title={t('rename')} disabled={busy} onClick={() => void renameTag(tag)}><Pencil size={15} /></button><button type="button" className="item-danger" aria-label={`${t('delete')} ${tag}`} title={t('delete')} disabled={busy} onClick={() => void removeTag(tag)}><Trash2 size={15} /></button></div></div>) : <p className="settings-empty">{t('noTags')}</p>}</div></div>
          <div className="settings-actions"><button type="button" className="primary" disabled={busy} onClick={() => void saveGeneral()}>{t('saveSettings')}</button></div>
        </section>}
        {section === 'security' && <section className="card setting-section" aria-labelledby="settings-security-title"><div className="card-title"><div><h2 id="settings-security-title">{t('securityStatus')}</h2><p>{t('securityStatusDescription')}</p></div></div>{security && <div className="security-summary"><div className="security-status-icon"><ShieldCheck size={20} /></div><div><strong>{security.kdf_algorithm}</strong><span>m={security.kdf_m_cost_kib}, t={security.kdf_t_cost}, p={security.kdf_parallelism}</span></div><span className={`status-badge ${security.recovery_enabled ? 'positive' : 'neutral'}`}><CheckCircle2 size={14} />{security.recovery_enabled ? t('recoveryEnabled') : t('recoveryDisabled')}</span></div>}<div className="plaintext-warning"><ShieldAlert size={18} /><div><strong>{t('httpBanner')}</strong><span>{t('noThrottleWarning')}</span></div></div></section>}
        {section === 'master' && <section className="card setting-section" aria-labelledby="settings-master-title"><div className="card-title"><div><h2 id="settings-master-title">{t('masterRecovery')}</h2><p>{t('masterRecoveryDescription')}</p></div></div><div className="settings-form modal-form"><div className="form-group"><label htmlFor="current-master">{t('currentMaster')}</label><input id="current-master" type="password" value={current} onChange={(event) => setCurrent(event.target.value)} /></div><div className="form-group"><label htmlFor="new-master">{t('newMaster')}</label><input id="new-master" type="password" value={next} onChange={(event) => setNext(event.target.value)} /></div><div className="form-group"><label htmlFor="confirm-master">{t('confirmNewMaster')}</label><input id="confirm-master" type="password" value={confirmNext} onChange={(event) => setConfirmNext(event.target.value)} /></div>{strengthOf(next) === 'weak' && <label className="auth-check"><input type="checkbox" checked={weakAck} onChange={(event) => setWeakAck(event.target.checked)} />{t('weakPasswordAck')}</label>}<div className="form-actions"><button type="button" className="primary" disabled={busy} onClick={() => void changeMaster()}>{t('changeMaster')}</button>{security?.recovery_enabled ? <><button type="button" className="secondary" disabled={busy} onClick={() => void recoveryAction('rotate')}>{t('rotateRecovery')}</button><button type="button" className="danger-outline" disabled={busy} onClick={() => void disableRecovery()}>{t('disableRecovery')}</button></> : <button type="button" className="secondary" disabled={busy} onClick={() => void recoveryAction('enable')}>{t('enableRecovery')}</button>}</div><div className="danger-zone"><div><h3><AlertTriangle size={16} />{t('dangerZone')}</h3><p>{t('resetVaultDescription')}</p></div><label htmlFor="reset-phrase">{t('resetPhrase')}</label><input id="reset-phrase" value={resetPhrase} onChange={(event) => setResetPhrase(event.target.value)} /><button type="button" className="danger-outline" disabled={busy} onClick={() => void reset()}>{t('resetVault')}</button></div></div></section>}
        {section === 'host' && host && <section className="card setting-section" aria-labelledby="settings-host-title"><div className="card-title"><div><h2 id="settings-host-title">{t('hostNetwork')}</h2><p>{t('hostNetworkDescription')}</p></div></div><div className="settings-fields"><div className="setting-row"><div className="setting-copy"><label className="setting-label" htmlFor="host-port"><strong>{t('port')}</strong><span>{t('portDescription')}</span></label></div><input id="host-port" className="setting-number" type="number" min="1024" max="65535" value={host.port} onChange={(event) => setHost({ ...host, port: Number(event.target.value) })} /></div><div className="setting-row"><div className="setting-copy"><label className="setting-label" htmlFor="host-autostart"><strong>{t('autostart')}</strong><span>{t('autostartDescription')}</span></label></div><input id="host-autostart" className="toggle-control" type="checkbox" checked={host.autostart} onChange={(event) => setHost({ ...host, autostart: event.target.checked })} /></div></div><div className="network-note"><Globe2 size={16} /><span>0.0.0.0 · {t('lanDefault')}</span></div><div className="settings-actions"><button type="button" className="primary" disabled={busy} onClick={() => void saveHost()}>{t('save')}</button></div></section>}
        {section === 'backup' && <section className="card setting-section backup-settings-card" aria-labelledby="settings-backup-title"><div className="card-title"><div><h2 id="settings-backup-title">{t('backup')}</h2><p>{t('backupSettingsDescription')}</p></div><DatabaseBackup size={24} className="section-watermark" /></div><div className="backup-settings-body"><p>{t('backupSettingsDetail')}</p><button type="button" className="primary" onClick={navigateBackup}>{t('openBackup')}</button></div></section>}
      </div>
    </div>
  </div>
}
