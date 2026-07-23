import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type FormEvent,
  type ReactNode,
} from 'react'
import {
  ArchiveRestore, ArrowDownUp, Check, ChevronDown, CircleHelp, Clipboard,
  Copy, DatabaseBackup, Download, Ellipsis, ExternalLink, Eye, EyeOff,
  FileDown, FileUp, Folder, Globe2, HardDrive, History, KeyRound,
  LockKeyhole, Menu, MoreHorizontal, Plus, RefreshCw, RotateCcw, Search,
  Settings, ShieldAlert, ShieldCheck, SlidersHorizontal, Sparkles, Star,
  Tags, Trash2, Upload, Vault, Wifi, X,
} from 'lucide-react'
import {
  ApiError, api, getToken, saveBlob, setToken, websocketUrl,
  type BackupItem, type Category, type Credential, type ImportPreview,
  type Lang, type SecurityStatus, type SessionResult, type VaultSettings,
} from './api'
import { useI18n } from './i18n'

import type { Screen, View, Modal } from './types'
import { colorFor, initials, relativeTime, errorText } from './utils/helpers'
import { IconButton } from './components/IconButton'
import { RecoveryKeyDialog } from './components/RecoveryKeyDialog'
import { AuthScreen } from './views/AuthScreen'
import { RowMenu } from './components/RowMenu'
import { BulkBar } from './components/BulkBar'
import { DetailPanel } from './components/DetailPanel'
import { CredentialDialog } from './components/CredentialDialog'
import { ExportDialog } from './components/ExportDialog'
import { ImportDialog } from './components/ImportDialog'
import { BackupView } from './views/BackupView'
import { SettingsView } from './views/SettingsView'
import { HelpDialog } from './components/HelpDialog'

export default function App() {
  const [lang, setLang] = useState<Lang>((localStorage.getItem('lv_lang') as Lang) || 'id')
  const { t } = useI18n(lang)
  useEffect(() => { document.documentElement.lang = lang }, [lang])
  const [screen, setScreen] = useState<Screen>('boot')
  const [view, setView] = useState<View>('vault')
  const [credentials, setCredentials] = useState<Credential[]>([])
  const [categories, setCategories] = useState<Category[]>([])
  const [tags, setTags] = useState<string[]>([])
  const [settings, setSettings] = useState<VaultSettings | null>(null)
  const [vaultRevision, setVaultRevision] = useState(0)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [selectedRows, setSelectedRows] = useState<string[]>([])
  const [query, setQuery] = useState('')
  const [categoryFilter, setCategoryFilter] = useState('all')
  const [tagFilters, setTagFilters] = useState<string[]>([])
  const [favoriteOnly, setFavoriteOnly] = useState(false)
  const [sort, setSort] = useState('updated')
  const [page, setPage] = useState(1)
  const [modal, setModal] = useState<Modal>(null)
  const [mobileNav, setMobileNav] = useState(false)
  const [isMobile, setIsMobile] = useState(() => matchMedia('(max-width: 767px)').matches)
  const [detailOpen, setDetailOpen] = useState(() => !matchMedia('(max-width: 767px)').matches)
  const [toast, setToast] = useState('')
  const [busy, setBusy] = useState(false)
  const [backups, setBackups] = useState<BackupItem[]>([])
  const [recoveryKey, setRecoveryKey] = useState<string | null>(null)
  const afterRecovery = useRef<(() => void) | null>(null)
  const toastTimer = useRef<number | null>(null)
  const searchRef = useRef<HTMLInputElement>(null)
  const reloadTimer = useRef<number | null>(null)
  const bootSettled = useRef(false)

  useEffect(() => {
    const query = matchMedia('(max-width: 767px)')
    const update = () => setIsMobile(query.matches)
    query.addEventListener('change', update)
    return () => query.removeEventListener('change', update)
  }, [])

  const announce = useCallback((message: string) => {
    if (toastTimer.current !== null) clearTimeout(toastTimer.current)
    setToast(message || t('requestFailed'))
    toastTimer.current = window.setTimeout(() => setToast(''), 3200)
  }, [t])

  const loadAll = useCallback(async () => {
    let attempts = 0
    while (attempts < 2) {
      attempts++
      const first = await api.listCredentials({ status: 'all', page: 1, page_size: 100 })
      const all = [...first.items]
      const revision = first.vault_revision
      const pages = Math.ceil(first.total / 100)
      for (let current = 2; current <= pages; current++) {
        const next = await api.listCredentials({ status: 'all', page: current, page_size: 100 })
        if (next.vault_revision !== revision) break
        all.push(...next.items)
      }
      if (all.length === first.total) {
        const [categoryResult, tagResult, generalResult] = await Promise.all([api.categories(), api.tags(), api.general()])
        setCredentials(all)
        setCategories(categoryResult.items)
        setTags(tagResult.items)
        setSettings(generalResult)
        setVaultRevision(revision)
        setLang(generalResult.language)
        localStorage.setItem('lv_lang', generalResult.language)
        setSelectedId((current) => current && all.some((item) => item.id === current) ? current : all.find((item) => !item.deleted_at)?.id || null)
        return
      }
    }
    throw new Error(t('vaultChangedRetry'))
  }, [t])

  const enterApp = useCallback(async () => {
    setScreen('app')
    try { await loadAll() } catch (error) { announce(errorText(error)) }
  }, [announce, loadAll])

  useEffect(() => {
    if (bootSettled.current) return
    let cancelled = false
    async function boot(): Promise<void> {
      try {
        const status = await api.status()
        if (cancelled) return
        if (status.setup_required) { bootSettled.current = true; setScreen('signup'); return }
        if (status.locked || !getToken()) { bootSettled.current = true; setToken(null); setScreen('login'); return }
        try { await api.current(); if (!cancelled) { bootSettled.current = true; await enterApp() } }
        catch { if (!cancelled) { bootSettled.current = true; setToken(null); setScreen('login') } }
      } catch { if (!cancelled) { bootSettled.current = true; setScreen('offline') } }
    }
    void boot()
    return () => { cancelled = true }
  }, [enterApp])

  useEffect(() => {
    function ended(): void {
      setCredentials([]); setCategories([]); setTags([]); setSelectedRows([]); setSelectedId(null); setModal(null); setScreen('login')
    }
    window.addEventListener('localvault:session-ended', ended)
    return () => window.removeEventListener('localvault:session-ended', ended)
  }, [])

  useEffect(() => {
    if (screen !== 'app') return
    let stopped = false
    let socket: WebSocket | null = null
    let retry: number | null = null
    async function connect(): Promise<void> {
      try {
        const { ticket } = await api.eventTicket()
        if (stopped) return
        socket = new WebSocket(websocketUrl(ticket))
        socket.onopen = () => socket?.send(JSON.stringify({ type: 'sync_state', last_seen_vault_revision: vaultRevision }))
        socket.onmessage = (event) => {
          const message = JSON.parse(event.data)
          if (message.type === 'vault.locked' || message.code === 'TAB_OWNERSHIP_CONFLICT') {
            setToken(null)
            window.dispatchEvent(new CustomEvent('localvault:session-ended', { detail: { code: message.type } }))
          } else if (message.type === 'vault.changed' || message.type === 'vault.reload_required') {
            if (reloadTimer.current !== null) clearTimeout(reloadTimer.current)
            reloadTimer.current = window.setTimeout(() => void loadAll().catch((error) => announce(errorText(error))), 80)
          }
        }
        socket.onclose = () => { if (!stopped) retry = window.setTimeout(() => void connect(), 700) }
      } catch (error) {
        if (!stopped) retry = window.setTimeout(() => void connect(), 700)
      }
    }
    void connect()
    return () => { stopped = true; if (retry !== null) clearTimeout(retry); socket?.close() }
  }, [announce, loadAll, screen, vaultRevision])

  useEffect(() => () => { if (toastTimer.current !== null) clearTimeout(toastTimer.current) }, [])

  const source = useMemo(() => view === 'trash' ? credentials.filter((item) => item.deleted_at) : credentials.filter((item) => !item.deleted_at), [credentials, view])
  const filtered = useMemo(() => {
    const needle = query.trim().toLocaleLowerCase(lang)
    const result = source.filter((item) => {
      const categoryName = categories.find((category) => category.id === item.category_id)?.name || ''
      const haystack = [item.name, item.username || '', item.url || '', item.notes, categoryName, ...item.tags, ...item.custom_fields.filter((field) => field.type === 'text').flatMap((field) => [field.label, field.value])].join(' ').toLocaleLowerCase(lang)
      const tagsMatch = tagFilters.length === 0 || (settings?.tag_filter_mode === 'or' ? tagFilters.some((tag) => item.tags.includes(tag)) : tagFilters.every((tag) => item.tags.includes(tag)))
      return (!needle || haystack.includes(needle)) && (categoryFilter === 'all' || item.category_id === categoryFilter) && tagsMatch && (!favoriteOnly || item.favorite) && (view !== 'favorites' || item.favorite)
    })
    const collator = new Intl.Collator(lang === 'id' ? 'id-ID' : 'en-US', { numeric: true, sensitivity: 'base' })
    return result.sort((left, right) => {
      if (sort === 'name') return collator.compare(left.name, right.name) || left.id.localeCompare(right.id)
      if (sort === 'nameD') return collator.compare(right.name, left.name) || left.id.localeCompare(right.id)
      if (sort === 'favorite') return Number(right.favorite) - Number(left.favorite) || collator.compare(left.name, right.name)
      return right.updated_at.localeCompare(left.updated_at) || left.id.localeCompare(right.id)
    })
  }, [categories, categoryFilter, favoriteOnly, lang, query, settings?.tag_filter_mode, sort, source, tagFilters, view])

  const pageSize = settings?.page_size || 50
  const pageCount = Math.max(1, Math.ceil(filtered.length / pageSize))
  const visible = filtered.slice((Math.min(page, pageCount) - 1) * pageSize, Math.min(page, pageCount) * pageSize)
  const selected = filtered.find((item) => item.id === selectedId) || visible[0] || null

  useEffect(() => { setPage(1); setSelectedRows((current) => current.filter((id) => filtered.some((item) => item.id === id))) }, [filtered])

  useEffect(() => {
    function shortcuts(event: KeyboardEvent): void {
      const typing = ['INPUT', 'TEXTAREA', 'SELECT'].includes((event.target as HTMLElement).tagName)
      if (event.key === '/' && !typing) { event.preventDefault(); searchRef.current?.focus() }
      if (event.key === '?' && !typing) { event.preventDefault(); setModal({ kind: 'help' }) }
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'n' && screen === 'app') { event.preventDefault(); setModal({ kind: 'credential', credential: null, generator: false }) }
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k' && screen === 'app') { event.preventDefault(); setModal({ kind: 'help' }) }
    }
    window.addEventListener('keydown', shortcuts)
    return () => window.removeEventListener('keydown', shortcuts)
  }, [screen])

  function handleAuth(result: SessionResult): void {
    setToken(result.token)
    if (result.recovery_key) {
      afterRecovery.current = () => void enterApp()
      setRecoveryKey(result.recovery_key)
    } else void enterApp()
  }

  async function lock(): Promise<void> {
    setBusy(true)
    try {
      await api.lock()
      setToken(null); setCredentials([]); setScreen('login')
    } catch (error) { announce(`${t('lockUnconfirmed')}: ${errorText(error)}`) }
    finally { setBusy(false) }
  }

  async function reload(): Promise<void> {
    try { await loadAll() } catch (error) { announce(errorText(error)) }
  }

  function navigate(next: View): void {
    setView(next); setMobileNav(false); setSelectedRows([]); setPage(1)
    if (next === 'backup') void api.backups().then((result) => setBackups(result.items)).catch((error) => announce(errorText(error)))
  }

  if (screen !== 'app') return <>
    <AuthScreen screen={screen} lang={lang} setLang={setLang} t={t} onSuccess={handleAuth} onScreen={setScreen} retry={() => location.reload()} />
    {recoveryKey && <RecoveryKeyDialog recoveryKey={recoveryKey} t={t} acknowledge={() => { setRecoveryKey(null); const action = afterRecovery.current; afterRecovery.current = null; action?.() }} />}
  </>

  return <div className="app-shell">
    <aside className={`sidebar ${mobileNav ? 'open' : ''}`} aria-hidden={isMobile && !mobileNav ? true : undefined} inert={isMobile && !mobileNav ? true : undefined}>
      <div className="brand"><span className="brand-mark"><LockKeyhole size={20} /></span><span>{t('appName')}</span></div>
      <button className="new-button" onClick={() => setModal({ kind: 'credential', credential: null, generator: false })}><Plus size={18} /> {t('newCredential')} <kbd>⌘N</kbd></button>
      <nav aria-label={t('mainNavigation')}>
        <p className="nav-label">VAULT</p>
        <button className={`nav-item ${view === 'vault' ? 'active' : ''}`} onClick={() => navigate('vault')}><Vault size={18} /><span>{t('allItems')}</span><small>{credentials.filter((item) => !item.deleted_at).length}</small></button>
        <button className={`nav-item ${view === 'favorites' ? 'active' : ''}`} onClick={() => navigate('favorites')}><Star size={18} /><span>{t('favorites')}</span><small>{credentials.filter((item) => !item.deleted_at && item.favorite).length}</small></button>
        <button className={`nav-item ${view === 'trash' ? 'active' : ''}`} onClick={() => navigate('trash')}><Trash2 size={18} /><span>{t('trash')}</span><small>{credentials.filter((item) => item.deleted_at).length}</small></button>
        <p className="nav-label category-label">{t('category')}</p>
        {categories.map((category) => <button className="nav-item category-item" key={category.id} onClick={() => { navigate('vault'); setCategoryFilter(category.id) }}><i style={{ background: colorFor(category.id) }} /><span>{category.name}</span></button>)}
      </nav>
      <div className="sidebar-footer">
        <button className={`nav-item ${view === 'backup' ? 'active' : ''}`} onClick={() => navigate('backup')}><DatabaseBackup size={18} /><span>{t('backup')}</span></button>
        <button className={`nav-item ${view === 'settings' ? 'active' : ''}`} onClick={() => navigate('settings')}><Settings size={18} /><span>{t('settings')}</span></button>
        <button className="nav-item mobile-help" onClick={() => setModal({ kind: 'help' })}><CircleHelp size={18} /><span>{t('help')}</span></button>
        <div className="vault-status"><ShieldCheck size={18} /><div><strong>{t('vaultProtected')}</strong><span>{t('connected')}</span></div><span className="status-light" /></div>
      </div>
    </aside>
    {mobileNav && <button className="nav-scrim" aria-label={t('closeMenu')} onClick={() => setMobileNav(false)} />}

    <main className="main-area">
      <div className="http-banner"><ShieldAlert size={16} /><span><strong>{t('httpBanner')}</strong></span><button onClick={() => setModal({ kind: 'help' })}>{t('learnRisk')}</button></div>
      <header className="topbar">
        <IconButton label={t('openMenu')} className="mobile-menu" onClick={() => setMobileNav(true)}><Menu size={20} /></IconButton>
        <div className="search-wrap"><Search size={18} /><input ref={searchRef} value={query} onChange={(event) => setQuery(event.target.value)} placeholder={t('searchPlaceholder')} aria-label={t('searchPlaceholder')} /><kbd>/</kbd>{query && <button onClick={() => setQuery('')} aria-label={t('clear')}><X size={15} /></button>}</div>
        <div className="top-actions"><span className="connection"><Wifi size={15} /> {t('connected')}</span><IconButton label={t('help')} onClick={() => setModal({ kind: 'help' })}><CircleHelp size={18} /></IconButton><button className="lock-button" disabled={busy} onClick={() => void lock()}><LockKeyhole size={16} /><span>{t('lock')}</span></button></div>
      </header>

      {view === 'backup'
        ? <BackupView backups={backups} setBackups={setBackups} announce={announce} t={t} onRestored={() => { setToken(null); setScreen('login') }} />
        : view === 'settings'
          ? <SettingsView lang={lang} settings={settings} categories={categories} tags={tags} vaultRevision={vaultRevision} t={t} announce={announce} reload={reload} setLang={setLang} showRecovery={(key, after) => { afterRecovery.current = after ?? null; setRecoveryKey(key) }} navigateBackup={() => navigate('backup')} />
          : <div className="workspace"><section className="list-pane">
            <div className="page-heading"><div><p className="eyebrow">{view === 'trash' ? t('temporaryStorage') : t('privateVault')}</p><h1>{view === 'trash' ? t('trash') : view === 'favorites' ? t('favorites') : t('allItems')}</h1><p>{filtered.length} {t('items')}</p></div>{view === 'trash' ? <button className="danger-outline" disabled={busy || source.length === 0} onClick={async () => { if (!confirm(t('confirmEmptyTrash').replace('{count}', String(source.length)))) return; setBusy(true); try { await api.emptyTrash(source.length); await reload(); announce(t('trashEmptied')) } catch (error) { announce(errorText(error)) } finally { setBusy(false) } }}><Trash2 size={16} /> {t('emptyTrash')}</button> : <div className="heading-actions"><button className="secondary" onClick={() => setModal({ kind: 'import' })}><FileUp size={16} /> {t('import')}</button><button className="secondary" onClick={() => setModal({ kind: 'export' })}><FileDown size={16} /> {t('export')}</button></div>}</div>
            <div className="toolbar"><div className="filter-group">
              <label className="select-control"><Folder size={15} /><select value={categoryFilter} onChange={(event) => setCategoryFilter(event.target.value)}><option value="all">{t('allCategories')}</option>{categories.map((category) => <option key={category.id} value={category.id}>{category.name}</option>)}</select><ChevronDown size={14} /></label>
              <button className={`filter-button ${favoriteOnly ? 'selected' : ''}`} onClick={() => setFavoriteOnly((value) => !value)}><Star size={15} /> {t('favorites')}</button>
              <label className="select-control"><Tags size={15} /><select value="" onChange={(event) => { const value = event.target.value; if (value && !tagFilters.includes(value)) setTagFilters([...tagFilters, value]) }}><option value="">{t('addTagFilter')}</option>{tags.filter((tag) => !tagFilters.includes(tag)).map((tag) => <option key={tag}>{tag}</option>)}</select></label>
              {tagFilters.map((tag) => <button key={tag} className="filter-button selected" onClick={() => setTagFilters(tagFilters.filter((value) => value !== tag))}>{tag} <X size={13} /></button>)}
              {(categoryFilter !== 'all' || tagFilters.length || favoriteOnly || query) ? <button className="reset-filter" onClick={() => { setCategoryFilter('all'); setTagFilters([]); setFavoriteOnly(false); setQuery('') }}>{t('resetFilters')}</button> : null}
            </div><label className="sort-control"><ArrowDownUp size={15} /><select value={sort} onChange={(event) => setSort(event.target.value)}><option value="updated">{t('lastChanged')}</option><option value="name">{t('nameAZ')}</option><option value="nameD">{t('nameZA')}</option><option value="favorite">{t('favorites')}</option></select></label></div>
            {selectedRows.length > 0 && <BulkBar selectedRows={selectedRows} filtered={filtered} credentials={credentials} view={view} t={t} announce={announce} reload={reload} clear={() => setSelectedRows([])} selectAll={() => setSelectedRows(filtered.map((item) => item.id))} />}
            <div className="table-card"><table><thead><tr><th className="check-cell"><input type="checkbox" aria-label={t('selectPage')} checked={visible.length > 0 && visible.every((item) => selectedRows.includes(item.id))} onChange={() => setSelectedRows(visible.every((item) => selectedRows.includes(item.id)) ? selectedRows.filter((id) => !visible.some((item) => item.id === id)) : Array.from(new Set([...selectedRows, ...visible.map((item) => item.id)])))} /></th><th /><th>{t('name')}</th><th>{t('username')}</th><th>URL</th><th>{t('category')}</th><th>{t('tags')}</th><th>{t('lastChanged')}</th><th /></tr></thead><tbody>
              {visible.map((item) => <tr key={item.id} className={selected?.id === item.id ? 'row-active' : ''} onClick={() => { setSelectedId(item.id); setDetailOpen(true) }}><td className="check-cell" onClick={(event) => event.stopPropagation()}><input type="checkbox" aria-label={`${t('select')} ${item.name}`} checked={selectedRows.includes(item.id)} onChange={() => setSelectedRows(selectedRows.includes(item.id) ? selectedRows.filter((id) => id !== item.id) : [...selectedRows, item.id])} /></td><td><Star size={16} fill={item.favorite ? 'currentColor' : 'none'} /></td><td><span className="credential-link"><span className="avatar avatar-sm" style={{ background: colorFor(item.id) }}>{initials(item.name)}</span><strong>{item.name}</strong></span></td><td className="hide-tablet">{item.username}</td><td className="url-cell hide-medium">{item.url}</td><td>{categories.find((category) => category.id === item.category_id)?.name || '—'}</td><td className="tags-cell hide-medium">{item.tags.slice(0, 2).map((tag) => <span key={tag}>{tag}</span>)}</td><td>{relativeTime(item.updated_at, lang)}</td><td onClick={(event) => event.stopPropagation()}><RowMenu item={item} t={t} edit={() => setModal({ kind: 'credential', credential: item, generator: false })} reload={reload} announce={announce} /></td></tr>)}
            </tbody></table>{visible.length === 0 && <div className="empty-state"><Search size={28} /><h3>{t('noResults')}</h3><p>{t('tryOther')}</p></div>}<div className="pagination"><span>{t('showing')} {visible.length} {t('of')} {filtered.length}</span><div><button disabled={page <= 1} onClick={() => setPage(page - 1)}>‹</button><span>{Math.min(page, pageCount)} / {pageCount}</span><button disabled={page >= pageCount} onClick={() => setPage(page + 1)}>›</button></div></div></div>
          </section>{selected && detailOpen && <DetailPanel item={selected} categories={categories} lang={lang} t={t} close={() => setDetailOpen(false)} announce={announce} reload={reload} edit={() => setModal({ kind: 'credential', credential: selected, generator: false })} generator={() => setModal({ kind: 'credential', credential: selected, generator: true })} />}</div>}
    </main>

    {modal?.kind === 'credential' && <CredentialDialog credential={modal.credential} startGenerator={modal.generator} categories={categories} t={t} announce={announce} close={() => setModal(null)} saved={reload} />}
    {modal?.kind === 'export' && <ExportDialog t={t} close={() => setModal(null)} announce={announce} filter={{ q: query, category: categoryFilter === 'all' ? '' : categoryFilter, tags: tagFilters, favorite_only: favoriteOnly, status: view === 'trash' ? 'trash' : 'active', tag_mode: settings?.tag_filter_mode || 'and', sort_field: sort === 'updated' ? 'updated_at' : sort === 'favorite' ? 'favorite' : 'name', sort_direction: sort === 'nameD' || sort === 'updated' ? 'desc' : 'asc' }} selectedIds={selectedRows} />}
    {modal?.kind === 'import' && <ImportDialog t={t} close={() => setModal(null)} announce={announce} saved={reload} />}
    {modal?.kind === 'help' && <HelpDialog t={t} close={() => setModal(null)} />}
    {recoveryKey && <RecoveryKeyDialog recoveryKey={recoveryKey} t={t} acknowledge={() => { setRecoveryKey(null); const action = afterRecovery.current; afterRecovery.current = null; action?.() }} />}
    <div className={`toast ${toast ? 'show' : ''}`} role="status" aria-live="polite"><Check size={17} />{toast}</div>
  </div>
}
