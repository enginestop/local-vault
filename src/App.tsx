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

type Screen = 'boot' | 'app' | 'login' | 'signup' | 'recover' | 'offline'
type View = 'vault' | 'favorites' | 'trash' | 'backup' | 'settings'
type Modal =
  | { kind: 'credential'; credential: Credential | null; generator: boolean }
  | { kind: 'export' }
  | { kind: 'import' }
  | { kind: 'help' }
  | null

const COLORS = ['#1f2937', '#a855f7', '#f59e0b', '#e50914', '#16a34a', '#f97316', '#4d87b8', '#a66ad1']

function colorFor(id: string): string {
  let hash = 0
  for (const character of id) hash = (hash * 31 + character.charCodeAt(0)) >>> 0
  return COLORS[hash % COLORS.length]
}

function initials(name: string): string {
  const parts = name.trim().split(/\s+/)
  return (parts.length > 1 ? parts[0][0] + parts[1][0] : parts[0].slice(0, 2)).toUpperCase()
}

function strengthOf(password: string): 'weak' | 'good' | 'strong' {
  let score = 0
  if (password.length >= 12) score++
  if (password.length >= 18) score++
  if (/[a-z]/.test(password) && /[A-Z]/.test(password)) score++
  if (/\d/.test(password)) score++
  if (/[^a-zA-Z0-9]/.test(password)) score++
  return score >= 4 ? 'strong' : score >= 2 ? 'good' : 'weak'
}

function relativeTime(value: string, lang: Lang): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  const seconds = Math.round((date.getTime() - Date.now()) / 1000)
  const formatter = new Intl.RelativeTimeFormat(lang === 'id' ? 'id-ID' : 'en-US', { numeric: 'auto' })
  if (Math.abs(seconds) < 60) return formatter.format(seconds, 'second')
  const minutes = Math.round(seconds / 60)
  if (Math.abs(minutes) < 60) return formatter.format(minutes, 'minute')
  const hours = Math.round(minutes / 60)
  if (Math.abs(hours) < 24) return formatter.format(hours, 'hour')
  return formatter.format(Math.round(hours / 24), 'day')
}

function errorText(error: unknown): string {
  if (error instanceof ApiError) return error.requestId ? `${error.detail} (${error.requestId})` : error.detail
  return error instanceof Error && error.message ? error.message : 'Request failed'
}

function IconButton({ label, children, onClick, className = '' }: { label: string; children: ReactNode; onClick?: () => void; className?: string }) {
  return <button type="button" className={`icon-button ${className}`} aria-label={label} title={label} onClick={onClick}>{children}</button>
}

function NativeDialog({ title, close, closeLabel, children, busy = false }: { title: string; close: () => void; closeLabel?: string; children: ReactNode; busy?: boolean }) {
  const ref = useRef<HTMLDialogElement>(null)
  const opener = useRef<HTMLElement | null>(null)
  const accessibleClose = closeLabel || (document.documentElement.lang === 'id' ? 'Tutup' : 'Close')
  useEffect(() => {
    opener.current = document.activeElement as HTMLElement | null
    ref.current?.showModal()
    return () => opener.current?.focus()
  }, [])
  return <dialog ref={ref} className="modal native-dialog" aria-labelledby="dialog-title" onCancel={(event) => { if (busy) event.preventDefault(); else close() }} onClose={() => !busy && close()}>
    <div className="modal-header"><div><p className="eyebrow">LOCALVAULT</p><h2 id="dialog-title">{title}</h2></div><IconButton label={accessibleClose} onClick={() => !busy && close()}><X size={20} /></IconButton></div>
    {children}
  </dialog>
}

function RecoveryKeyDialog({ recoveryKey, acknowledge, t }: { recoveryKey: string; acknowledge: () => void; t: (key: any) => string }) {
  const [saved, setSaved] = useState(false)
  async function copy(): Promise<void> {
    await navigator.clipboard.writeText(recoveryKey)
  }
  function download(): void {
    saveBlob({ blob: new Blob([`${recoveryKey}\n`], { type: 'text/plain' }), filename: 'localvault-recovery-key.txt' })
  }
  return <NativeDialog title={t('recoveryKey')} closeLabel={t('close')} close={() => {}} busy>
    <div className="modal-form">
      <div className="plaintext-warning"><ShieldAlert size={18} /><div><strong>{t('saveRecoveryNow')}</strong><span>{t('recoveryShownOnce')}</span></div></div>
      <div className="generated-box"><span>{recoveryKey}</span><IconButton label={t('copy')} onClick={() => void copy()}><Copy size={17} /></IconButton></div>
      <div className="modal-actions"><button type="button" className="secondary" onClick={download}><Download size={16} /> {t('download')}</button></div>
      <label className="auth-check"><input type="checkbox" checked={saved} onChange={(event) => setSaved(event.target.checked)} /><span>{t('recoverySavedAck')}</span></label>
      <button className="primary wide" disabled={!saved} onClick={acknowledge}>{t('continue')}</button>
    </div>
  </NativeDialog>
}

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
        if (!status.setup_completed) { bootSettled.current = true; setScreen('signup'); return }
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

function AuthScreen({ screen, lang, setLang, t, onSuccess, onScreen, retry }: { screen: Screen; lang: Lang; setLang: (lang: Lang) => void; t: (key: any) => string; onSuccess: (result: SessionResult) => void; onScreen: (screen: Screen) => void; retry: () => void }) {
  const [master, setMaster] = useState('')
  const [confirmation, setConfirmation] = useState('')
  const [recovery, setRecovery] = useState('')
  const [createRecovery, setCreateRecovery] = useState(true)
  const [riskAck, setRiskAck] = useState(false)
  const [weakAck, setWeakAck] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  if (screen === 'boot') return <div className="auth-page loading-state"><RefreshCw className="spin" /><p>{t('loading')}</p></div>
  if (screen === 'offline') return <div className="auth-page loading-state"><ShieldAlert /><h1>{t('serverUnavailable')}</h1><button className="primary" onClick={retry}>{t('retry')}</button></div>
  const isLogin = screen === 'login'
  const isRecover = screen === 'recover'
  const strength = strengthOf(master)
  async function submit(event: FormEvent): Promise<void> {
    event.preventDefault(); setBusy(true); setError('')
    try {
      if (isLogin) onSuccess(await api.unlock(master))
      else if (isRecover) onSuccess(await api.recover({ recovery_key: recovery, new_master_password: master, confirm_new_master_password: confirmation, weak_password_acknowledged: weakAck }))
      else onSuccess(await api.setup({ master_password: master, confirm_master_password: confirmation, create_recovery_key: createRecovery, language: lang, weak_password_acknowledged: weakAck, http_lan_risk_acknowledged: riskAck }))
    } catch (reason) { setError(errorText(reason)) }
    finally { setBusy(false) }
  }
  return <div className="auth-page"><div className="http-banner auth-banner"><ShieldAlert size={16} /><strong>{t('httpBanner')}</strong></div><header className="auth-header"><div className="brand auth-brand"><span className="brand-mark"><LockKeyhole size={20} /></span>{t('appName')}</div><div className="auth-connection"><Wifi size={16} />{t('lanActive')}</div></header><main className="auth-layout"><section className="auth-intro"><p className="auth-kicker">{t('privateNoCloud')}</p><h1>{isRecover ? t('recover') : isLogin ? t('loginTitle') : t('signupTitle')}</h1></section><section className="auth-card"><form className="auth-form" onSubmit={(event) => void submit(event)}>
    {isRecover && <label><span>{t('recoveryKey')}</span><div className="auth-input"><KeyRound size={18} /><input required value={recovery} onChange={(event) => setRecovery(event.target.value)} /></div></label>}
    <label><span>{isRecover ? t('newMaster') : t('masterPassword')}</span><div className="auth-input"><LockKeyhole size={18} /><input type="password" required value={master} onChange={(event) => setMaster(event.target.value)} /></div></label>
    {!isLogin && <><label><span>{t('confirmMaster')}</span><div className="auth-input"><ShieldCheck size={18} /><input type="password" required value={confirmation} onChange={(event) => setConfirmation(event.target.value)} /></div></label><div className="strength-row"><span>{t('passwordStrength')}</span><strong>{t(strength)}</strong></div>{strength === 'weak' && <label className="auth-check"><input type="checkbox" checked={weakAck} onChange={(event) => setWeakAck(event.target.checked)} /><span>{t('weakPasswordAck')}</span></label>}</>}
    {screen === 'signup' && <><label className="auth-check"><input type="checkbox" checked={createRecovery} onChange={(event) => setCreateRecovery(event.target.checked)} /><span>{t('createRecovery')}</span></label><label className="auth-check"><input type="checkbox" required checked={riskAck} onChange={(event) => setRiskAck(event.target.checked)} /><span>{t('understandRisk')}</span></label><label className="auth-select"><span>{t('language')}</span><select value={lang} onChange={(event) => setLang(event.target.value as Lang)}><option value="id">Bahasa Indonesia</option><option value="en">English</option></select></label></>}
    {error && <p className="form-error">{error}</p>}<button className="primary auth-submit" disabled={busy || (!isLogin && strength === 'weak' && !weakAck)}>{busy ? t('working') : isLogin ? t('openVault') : isRecover ? t('recover') : t('createOpen')}</button>
  </form>{isLogin && <button className="link-button" onClick={() => onScreen('recover')}>{t('useRecovery')}</button>}{isRecover && <button className="link-button" onClick={() => onScreen('login')}>{t('switchToLogin')}</button>}<div className="auth-switch"><button type="button" onClick={retry}>{t('retry')}</button></div></section></main></div>
}

function RowMenu({ item, edit, reload, announce, t }: { item: Credential; edit: () => void; reload: () => Promise<void>; announce: (value: string) => void; t: (key: any) => string }) {
  const [pending, setPending] = useState(false)
  async function action(kind: 'favorite' | 'trash' | 'restore' | 'purge'): Promise<void> {
    if (pending) return
    if ((kind === 'trash' || kind === 'purge') && !confirm(`${t('confirmAction')} ${item.name}?`)) return
    setPending(true)
    try {
      if (kind === 'favorite') await api.updateCredential(item.id, { favorite: !item.favorite }, item.revision)
      else if (kind === 'trash') await api.trashCredential(item.id, item.revision)
      else if (kind === 'restore') await api.restoreCredential(item.id, item.revision)
      else await api.purgeCredential(item.id, item.revision)
      await reload()
    } catch (error) { announce(errorText(error)) } finally { setPending(false) }
  }
  return <details className="row-menu"><summary aria-label={t('actions')}><MoreHorizontal size={18} /></summary><div><button onClick={edit}>{t('edit')}</button><button onClick={() => void action('favorite')}>{t('favorites')}</button>{item.deleted_at ? <><button onClick={() => void action('restore')}>{t('recover')}</button><button onClick={() => void action('purge')}>{t('deletePermanent')}</button></> : <button onClick={() => void action('trash')}>{t('moveTrash')}</button>}</div></details>
}

function BulkBar({ selectedRows, filtered, credentials, view, t, announce, reload, clear, selectAll }: { selectedRows: string[]; filtered: Credential[]; credentials: Credential[]; view: View; t: (key: any) => string; announce: (value: string) => void; reload: () => Promise<void>; clear: () => void; selectAll: () => void }) {
  const [pending, setPending] = useState(false)
  const selected = credentials.filter((item) => selectedRows.includes(item.id))
  async function apply(action: string): Promise<void> {
    if (pending) return
    if (['trash', 'purge'].includes(action) && !confirm(t('confirmBulk').replace('{count}', String(selected.length)))) return
    setPending(true)
    try { await api.bulk(action, selected); await reload(); clear() } catch (error) { announce(errorText(error)) } finally { setPending(false) }
  }
  const allSelected = filtered.length > 0 && filtered.every((item) => selectedRows.includes(item.id))
  return <div className="bulk-bar"><strong>{selected.length} {t('selected')}</strong><button onClick={allSelected ? clear : selectAll}>{t('selectAllResults')}</button><button onClick={() => void apply('set_favorite')}><Star size={15} /> {t('favorites')}</button>{view === 'trash' ? <><button onClick={() => void apply('restore')}><ArchiveRestore size={15} /> {t('recover')}</button><button className="bulk-danger" onClick={() => void apply('purge')}><Trash2 size={15} /> {t('deletePermanent')}</button></> : <button className="bulk-danger" onClick={() => void apply('trash')}><Trash2 size={15} /> {t('moveTrash')}</button>}</div>
}

function DetailPanel({ item, categories, lang, t, close, announce, reload, edit, generator }: { item: Credential; categories: Category[]; lang: Lang; t: (key: any) => string; close: () => void; announce: (value: string) => void; reload: () => Promise<void>; edit: () => void; generator: () => void }) {
  const [revealed, setRevealed] = useState(false)
  const [historyOpen, setHistoryOpen] = useState(false)
  async function copy(label: string, value: string): Promise<void> { try { await navigator.clipboard.writeText(value); announce(`${label} ${t('copiedClipboard')}`) } catch { announce(t('clipboardBlocked')) } }
  function openUrl(): void {
    if (!item.url) return
    let parsed: URL
    try { parsed = new URL(item.url) } catch { announce(t('invalidUrl')); return }
    if (!['http:', 'https:'].includes(parsed.protocol)) { announce(t('unsupportedUrlScheme')); return }
    if (confirm(`${t('openExternalUrl')}\n${parsed.toString()}`)) window.open(parsed.toString(), '_blank', 'noopener,noreferrer')
  }
  async function remove(): Promise<void> {
    if (!confirm(`${t('confirmAction')} ${item.name}?`)) return
    try { if (item.deleted_at) await api.purgeCredential(item.id, item.revision); else await api.trashCredential(item.id, item.revision); await reload(); close() } catch (error) { announce(errorText(error)) }
  }
  return <aside className="detail-panel" aria-label={`${t('detail')} ${item.name}`}><div className="detail-top"><span>{t('detail')}</span><IconButton label={t('close')} onClick={close}><X size={19} /></IconButton></div><div className="detail-scroll"><div className="detail-identity"><span className="avatar avatar-lg" style={{ background: colorFor(item.id) }}>{initials(item.name)}</span><div><h2>{item.name}</h2>{item.url && <button className="link-button" onClick={openUrl}>{item.url} <ExternalLink size={13} /></button>}</div></div><div className="detail-section"><Field label={t('username')} value={item.username || ''} action={<IconButton label={`${t('copy')} ${t('username')}`} onClick={() => void copy(t('username'), item.username || '')}><Copy size={16} /></IconButton>} /><Field label={t('password')} value={revealed ? item.password : '••••••••••••'} action={<><IconButton label={t('reveal')} onClick={() => setRevealed(!revealed)}>{revealed ? <EyeOff size={16} /> : <Eye size={16} />}</IconButton><IconButton label={`${t('copy')} ${t('password')}`} onClick={() => void copy(t('password'), item.password)}><Copy size={16} /></IconButton></>} /><button className="generate-link" onClick={generator}><Sparkles size={15} /> {t('generateNew')}</button></div><div className="detail-section"><p>{item.notes || t('noNotes')}</p></div><div className="detail-section"><button className="history-button" onClick={() => setHistoryOpen(!historyOpen)}><History size={16} /><span>{t('history')} ({item.password_history.length})</span></button>{historyOpen && item.password_history.map((entry) => <Field key={entry.id} label={relativeTime(entry.changed_at, lang)} value="••••••••" action={<IconButton label={`${t('copy')} ${t('password')}`} onClick={() => void copy(t('password'), entry.password)}><Copy size={16} /></IconButton>} />)}</div></div><div className="detail-actions"><button className="secondary grow" onClick={edit}><SlidersHorizontal size={16} /> {t('edit')}</button><button className="danger-icon" onClick={() => void remove()}><Trash2 size={17} /></button></div></aside>
}

function Field({ label, value, action }: { label: string; value: string; action: ReactNode }) { return <div className="field"><label>{label}</label><div className="field-box"><span>{value}</span><div>{action}</div></div></div> }

function CredentialDialog({ credential, startGenerator, categories, t, announce, close, saved }: { credential: Credential | null; startGenerator: boolean; categories: Category[]; t: (key: any) => string; announce: (value: string) => void; close: () => void; saved: () => Promise<void> }) {
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
  const generate = useCallback(async () => { try { const result = await api.generate({ length, include_lowercase: sets.lower, include_uppercase: sets.upper, include_digits: sets.digits, include_symbols: sets.symbols, exclude_ambiguous: sets.ambiguous }); setGenerated(result.password) } catch (error) { announce(errorText(error)) } }, [announce, length, sets])
  useEffect(() => { if (generator) void generate() }, [generator, generate])
  async function submit(event: FormEvent): Promise<void> {
    event.preventDefault(); setBusy(true)
    try { const body = { name, username: username || null, url: url || null, password, notes, tags: tagValue.split(',').map((tag) => tag.trim()).filter(Boolean), category_id: category || null }; if (credential) await api.updateCredential(credential.id, body, credential.revision); else await api.createCredential(body); await saved(); announce(t('saved')); close() } catch (error) { announce(errorText(error)) } finally { setBusy(false) }
  }
  return <NativeDialog title={generator ? t('generator') : credential ? t('edit') : t('newCredential')} close={close} busy={busy}>{generator ? <div className="generator-content"><div className="generated-box"><span>{generated || '—'}</span><IconButton label={t('copy')} onClick={() => void navigator.clipboard.writeText(generated)}><Clipboard size={17} /></IconButton></div><label className="range-label">{t('length')} {length}<input type="range" min="4" max="256" value={length} onChange={(event) => setLength(Number(event.target.value))} /></label><div className="charset-grid">{(['lower', 'upper', 'digits', 'symbols'] as const).map((key) => <label key={key}><input type="checkbox" checked={sets[key]} onChange={(event) => setSets({ ...sets, [key]: event.target.checked })} />{t(key)}</label>)}<label><input type="checkbox" checked={sets.ambiguous} onChange={(event) => setSets({ ...sets, ambiguous: event.target.checked })} />{t('excludeAmbiguous')}</label></div><div className="modal-actions"><button className="secondary" onClick={() => void generate()}>{t('regenerate')}</button><button className="primary" disabled={!generated} onClick={() => { setPassword(generated); setGenerator(false) }}>{t('usePassword')}</button></div></div> : <form className="modal-form" onSubmit={(event) => void submit(event)}><label>{t('name')}<input autoFocus required value={name} onChange={(event) => setName(event.target.value)} /></label><div className="form-row"><label>{t('username')}<input value={username} onChange={(event) => setUsername(event.target.value)} /></label><label>{t('category')}<select value={category} onChange={(event) => setCategory(event.target.value)}><option value="">—</option>{categories.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label></div><label>URL<input value={url} onChange={(event) => setUrl(event.target.value)} /></label><label>{t('password')}<div className="input-with-action"><input type="password" value={password} onChange={(event) => setPassword(event.target.value)} /><button type="button" onClick={() => setGenerator(true)}><Sparkles size={15} />{t('generateNew')}</button></div></label><label>{t('tags')}<input value={tagValue} onChange={(event) => setTagValue(event.target.value)} /></label><label>{t('notes')}<textarea rows={3} value={notes} onChange={(event) => setNotes(event.target.value)} /></label><div className="modal-actions"><button type="button" className="secondary" onClick={close}>{t('cancel')}</button><button className="primary" disabled={busy}>{t('save')}</button></div></form>}</NativeDialog>
}

function ExportDialog({ t, close, announce, filter, selectedIds }: { t: (key: any) => string; close: () => void; announce: (value: string) => void; filter: Record<string, unknown>; selectedIds: string[] }) {
  const [busy, setBusy] = useState(false)
  async function submit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault(); setBusy(true)
    const data = new FormData(event.currentTarget)
    try { const scope = String(data.get('scope')); const result = await api.exportVault({ master_password: data.get('password'), profile: data.get('profile'), scope, filter, selected_ids: scope === 'selected' ? selectedIds : [] }); saveBlob(result); announce(t('exportSuccess')); close() } catch (error) { announce(errorText(error)) } finally { setBusy(false) }
  }
  return <NativeDialog title={t('export')} close={close} busy={busy}><form className="modal-form" onSubmit={(event) => void submit(event)}><div className="plaintext-warning"><ShieldAlert size={18} /><div><strong>{t('plaintextWarning')}</strong><span>{t('plaintextDetail')}</span></div></div><label>{t('profile')}<select name="profile"><option value="spreadsheet">{t('spreadsheet')}</option><option value="chromium">Chromium</option><option value="firefox">Firefox</option></select></label><label>{t('scope')}<select name="scope"><option value="all">{t('all')}</option><option value="filtered">{t('filtered')}</option>{selectedIds.length > 0 && <option value="selected">{t('selectedItems')}</option>}</select></label><label>{t('confirmExport')}<input type="password" name="password" required /></label><div className="modal-actions"><button type="button" className="secondary" onClick={close}>{t('cancel')}</button><button className="primary" disabled={busy}>{t('export')}</button></div></form></NativeDialog>
}

function ImportDialog({ t, close, announce, saved }: { t: (key: any) => string; close: () => void; announce: (value: string) => void; saved: () => Promise<void> }) {
  const [file, setFile] = useState<File | null>(null)
  const [profile, setProfile] = useState('auto')
  const [delimiter, setDelimiter] = useState('')
  const [preview, setPreview] = useState<ImportPreview | null>(null)
  const [mapping, setMapping] = useState<Record<string, unknown>>({})
  const [resolutions, setResolutions] = useState<Record<number, string>>({})
  const [busy, setBusy] = useState(false)
  async function create(): Promise<void> { if (!file) return; setBusy(true); try { const result = await api.importPreview(file, profile, delimiter || null); setPreview(result); setMapping(result.mapping); setResolutions(Object.fromEntries(result.sample.map((row) => [row.row_number, row.resolution]))) } catch (error) { announce(errorText(error)) } finally { setBusy(false) } }
  const importChanges = () => ({ mapping, resolutions: Object.entries(resolutions).map(([row_number, resolution]) => ({ row_number: Number(row_number), resolution })) })
  async function update(): Promise<void> { if (!preview) return; setBusy(true); try { setPreview(await api.updateImport(preview.id, importChanges())) } catch (error) { announce(errorText(error)) } finally { setBusy(false) } }
  async function commit(): Promise<void> { if (!preview || !confirm(t('confirmImport').replace('{count}', String(preview.valid_count)))) return; setBusy(true); try { const refreshed = await api.updateImport(preview.id, importChanges()); setPreview(refreshed); const result = await api.commitImport(preview.id); await saved(); announce(t('importedCount').replace('{count}', String(result.committed))); close() } catch (error) { announce(errorText(error)) } finally { setBusy(false) } }
  return <NativeDialog title={t('import')} close={close} busy={busy}><div className="modal-form">{!preview ? <><div className="drop-zone"><Upload size={25} /><strong>{t('dropCsv')}</strong><input type="file" accept=".csv,text/csv" onChange={(event) => setFile(event.target.files?.[0] || null)} /></div><div className="form-row"><label>{t('preset')}<select value={profile} onChange={(event) => setProfile(event.target.value)}><option value="auto">{t('autoDetect')}</option><option value="generic">Generic</option><option value="chromium">Chromium</option><option value="firefox">Firefox</option><option value="localvault">LocalVault</option></select></label><label>{t('delimiter')}<select value={delimiter} onChange={(event) => setDelimiter(event.target.value)}><option value="">{t('autoDetect')}</option><option value=",">{t('comma')}</option><option value=";">{t('semicolon')}</option><option value={'\t'}>{t('tab')}</option></select></label></div><div className="modal-actions"><button className="secondary" onClick={close}>{t('cancel')}</button><button className="primary" disabled={!file || busy} onClick={() => void create()}>{t('continue')}</button></div></> : <><p>{t('valid')}: {preview.valid_count} · {t('invalid')}: {preview.invalid_count} · {t('conflicts')}: {preview.conflict_count}</p>{preview.warnings.map((warning) => <p className="form-warning" key={warning}>{warning}</p>)}<div className="mapping-grid">{preview.source_columns.map((column) => <label key={column}>{column}<select value={String(mapping[column] || 'ignore')} onChange={(event) => setMapping({ ...mapping, [column]: event.target.value })}>{['ignore', 'name', 'url', 'username', 'password', 'category', 'tags', 'favorite', 'notes', 'created_at', 'updated_at', 'custom_fields_json'].map((target) => <option key={target} value={target}>{target}</option>)}</select></label>)}</div>{preview.sample.filter((row) => row.conflict).map((row) => <label key={row.row_number}>{row.data.name || `#${row.row_number}`}<select value={resolutions[row.row_number] || 'skip'} onChange={(event) => setResolutions({ ...resolutions, [row.row_number]: event.target.value })}><option value="skip">Skip</option><option value="update">Update</option><option value="keep_both">Keep both</option></select></label>)}{preview.invalid_count > 0 && <p>{t('invalidRowsAvailable')} <button className="link-button" onClick={async () => { try { saveBlob(await api.downloadImportErrors(preview.id)) } catch (error) { announce(errorText(error)) } }}>{t('download')}</button></p>}<div className="modal-actions"><button className="secondary" onClick={close}>{t('cancel')}</button><button className="secondary" onClick={() => void update()}>{t('refreshPreview')}</button><button className="primary" disabled={busy} onClick={() => void commit()}>{t('import')}</button></div></>}</div></NativeDialog>
}

function BackupView({ backups, setBackups, announce, t, onRestored }: { backups: BackupItem[]; setBackups: (items: BackupItem[]) => void; announce: (value: string) => void; t: (key: any) => string; onRestored: () => void }) {
  const [file, setFile] = useState<File | null>(null)
  const [key, setKey] = useState('')
  const [busy, setBusy] = useState(false)
  async function refresh(): Promise<void> { setBackups((await api.backups()).items) }
  async function manual(): Promise<void> { setBusy(true); try { await api.manualBackup(); await refresh(); announce(t('backupCreated')) } catch (error) { announce(errorText(error)) } finally { setBusy(false) } }
  async function download(item: BackupItem): Promise<void> { try { saveBlob(await api.downloadBackup(item.backup_id)) } catch (error) { announce(errorText(error)) } }
  async function restore(input: { backupId?: string; file?: File }): Promise<void> { if (!confirm(t('restoreWarning'))) return; setBusy(true); try { await api.restoreBackup({ ...input, masterPassword: key || undefined, recoveryKey: key || undefined }); setToken(null); onRestored() } catch (error) { announce(errorText(error)) } finally { setBusy(false) } }
  return <div className="single-page"><div className="page-heading backup-heading"><div><h1>{t('backupRestore')}</h1></div><button className="primary" disabled={busy} onClick={() => void manual()}><DatabaseBackup size={17} />{t('createBackup')}</button></div><section className="card backups-card"><div className="backup-list">{backups.map((item) => <div className="backup-row" key={item.backup_id}><ArchiveRestore /><div><strong>r{item.vault_revision}</strong><span>{item.kind}</span></div><span className="backup-type">{item.kind}</span><div className="backup-info"><span>{item.created_at}</span></div><span className="valid"><Check size={13} />{item.valid ? t('valid') : t('invalid')}</span><IconButton label={t('download')} onClick={() => void download(item)}><Download size={17} /></IconButton><IconButton label={t('restore')} onClick={() => void restore({ backupId: item.backup_id })}><RotateCcw size={17} /></IconButton></div>)}</div></section><aside className="card restore-card"><Upload /><h2>{t('restoreFromFile')}</h2><input type="file" accept=".lvbak" onChange={(event) => setFile(event.target.files?.[0] || null)} /><input type="password" placeholder={t('historicalKeyOptional')} value={key} onChange={(event) => setKey(event.target.value)} /><button className="secondary wide" disabled={!file || busy} onClick={() => file && void restore({ file })}>{t('restore')}</button></aside></div>
}

function SettingsView({ lang, settings, categories, tags, vaultRevision, t, announce, reload, setLang, showRecovery, navigateBackup }: { lang: Lang; settings: VaultSettings | null; categories: Category[]; tags: string[]; vaultRevision: number; t: (key: any) => string; announce: (value: string) => void; reload: () => Promise<void>; setLang: (lang: Lang) => void; showRecovery: (key: string, after?: () => void) => void; navigateBackup: () => void }) {
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
  const load = useCallback(async () => { setLoadError(''); try { const [sec, hostResult] = await Promise.all([api.security(), api.host()]); setSecurity(sec); setHost({ port: hostResult.port, autostart: hostResult.autostart }) } catch (error) { setLoadError(errorText(error)) } }, [])
  useEffect(() => { void load() }, [load])
  useEffect(() => { if (settings) { setTagMode(settings.tag_filter_mode); setPageSize(settings.page_size); setDraftLang(settings.language) } }, [settings])
  async function saveGeneral(): Promise<void> { setBusy(true); try { await api.updateGeneral({ language: draftLang, tag_filter_mode: tagMode, page_size: pageSize }); setLang(draftLang); localStorage.setItem('lv_lang', draftLang); await reload(); announce(t('saved')) } catch (error) { announce(errorText(error)) } finally { setBusy(false) } }
  async function changeMaster(): Promise<void> { setBusy(true); try { await api.changeMaster({ current_master_password: current, new_master_password: next, confirm_new_master_password: confirmNext, weak_password_acknowledged: weakAck }); announce(t('masterChanged')); setCurrent(''); setNext(''); setConfirmNext('') } catch (error) { announce(errorText(error)) } finally { setBusy(false) } }
  async function recoveryAction(action: 'enable' | 'rotate' | 'disable'): Promise<void> { if (action === 'disable' && !confirm(t('confirmDisableRecovery'))) return; setBusy(true); try { const result = await api.recoveryAction(action, current); if (result.recovery_key) showRecovery(result.recovery_key); await load() } catch (error) { announce(errorText(error)) } finally { setBusy(false) } }
  async function reset(): Promise<void> { if (resetPhrase !== 'RESET LOCALVAULT' || !confirm(t('confirmReset'))) return; setBusy(true); try { const result = await api.resetVault({ master_password: current, confirm_recovery_phrase: resetPhrase, new_master_password: next, confirm_new_master_password: confirmNext, weak_password_acknowledged: weakAck, create_recovery_key: true }); if (result.recovery_key) showRecovery(result.recovery_key, () => { setToken(null); location.reload() }); else { setToken(null); location.reload() } } catch (error) { announce(errorText(error)) } finally { setBusy(false) } }
  async function saveHost(): Promise<void> { if (!host) return; setBusy(true); try { const result = await api.updateHost(host); announce(result.restart_required ? t('restartRequired') : t('saved')) } catch (error) { announce(errorText(error)) } finally { setBusy(false) } }
  async function createCategory(): Promise<void> { const name = prompt(t('createCategory')); if (!name) return; try { await api.createCategory(name); await reload() } catch (error) { announce(errorText(error)) } }
  async function renameCategory(category: Category): Promise<void> { if (busy) return; const name = prompt(t('renameCategory'), category.name); if (!name) return; setBusy(true); try { await api.updateCategory(category.id, name, category.revision); await reload() } catch (error) { announce(errorText(error)) } finally { setBusy(false) } }
  async function removeCategory(category: Category): Promise<void> { if (busy || !confirm(`${t('confirmAction')} ${category.name}?`)) return; setBusy(true); try { await api.deleteCategory(category.id, category.revision); await reload() } catch (error) { announce(errorText(error)) } finally { setBusy(false) } }
  async function renameTag(tag: string): Promise<void> { if (busy) return; const name = prompt(t('renameTag'), tag); if (!name) return; setBusy(true); try { await api.renameTag(tag, name, vaultRevision); await reload() } catch (error) { announce(errorText(error)) } finally { setBusy(false) } }
  async function removeTag(tag: string): Promise<void> { if (busy || !confirm(`${t('confirmAction')} ${tag}?`)) return; setBusy(true); try { await api.deleteTag(tag, vaultRevision); await reload() } catch (error) { announce(errorText(error)) } finally { setBusy(false) } }
  async function createTag(): Promise<void> { const name = prompt(t('createTag')); if (!name) return; try { await api.createTag(name); await reload() } catch (error) { announce(errorText(error)) } }
  return <div className="single-page settings-page"><div className="page-heading"><h1>{t('settings')}</h1></div>{loadError && <div className="form-error">{loadError}<button onClick={() => void load()}>{t('retry')}</button></div>}<div className="settings-layout"><nav className="settings-nav">{(['general', 'security', 'master', 'host', 'backup'] as const).map((key) => <button key={key} className={section === key ? 'active' : ''} onClick={() => setSection(key)}>{t(key === 'master' ? 'masterRecovery' : key === 'host' ? 'hostNetwork' : key)}</button>)}</nav><div className="settings-content">
    {section === 'general' && <section className="card setting-section"><div className="card-title"><h2>{t('general')}</h2></div><div className="setting-row"><strong>{t('language')}</strong><select value={draftLang} onChange={(event) => setDraftLang(event.target.value as Lang)}><option value="id">Bahasa Indonesia</option><option value="en">English</option></select></div><div className="setting-row"><strong>{t('tagFilterMode')}</strong><select value={tagMode} onChange={(event) => setTagMode(event.target.value as 'and' | 'or')}><option value="and">AND</option><option value="or">OR</option></select></div><div className="setting-row"><strong>{t('itemsPerPage')}</strong><select value={pageSize} onChange={(event) => setPageSize(Number(event.target.value) as 25 | 50 | 100)}><option>25</option><option>50</option><option>100</option></select></div><div className="setting-row"><div><strong>{t('category')} <button onClick={() => void createCategory()}>{t('create')}</button></strong>{categories.map((category) => <span key={category.id}>{category.name} <button onClick={() => void renameCategory(category)}>{t('rename')}</button> <button onClick={() => void removeCategory(category)}>{t('delete')}</button></span>)}</div></div><div className="setting-row"><div><strong>{t('tags')} <button onClick={() => void createTag()}>{t('create')}</button></strong>{tags.map((tag) => <span key={tag}>{tag} <button onClick={() => void renameTag(tag)}>{t('rename')}</button> <button onClick={() => void removeTag(tag)}>{t('delete')}</button></span>)}</div></div><button className="primary save-settings" disabled={busy} onClick={() => void saveGeneral()}>{t('saveSettings')}</button></section>}
    {section === 'security' && <section className="card setting-section"><div className="card-title"><h2>{t('security')}</h2></div>{security && <div className="setting-row"><div><strong>{security.kdf_algorithm}</strong><span>m={security.kdf_m_cost_kib}, t={security.kdf_t_cost}, p={security.kdf_parallelism}</span></div><span>{security.recovery_enabled ? t('recoveryEnabled') : t('recoveryDisabled')}</span></div>}<div className="plaintext-warning"><ShieldAlert /><div><strong>{t('httpBanner')}</strong><span>{t('noThrottleWarning')}</span></div></div></section>}
    {section === 'master' && <section className="card setting-section"><div className="card-title"><h2>{t('masterRecovery')}</h2></div><div className="modal-form"><label>{t('currentMaster')}<input type="password" value={current} onChange={(event) => setCurrent(event.target.value)} /></label><label>{t('newMaster')}<input type="password" value={next} onChange={(event) => setNext(event.target.value)} /></label><label>{t('confirmNewMaster')}<input type="password" value={confirmNext} onChange={(event) => setConfirmNext(event.target.value)} /></label>{strengthOf(next) === 'weak' && <label><input type="checkbox" checked={weakAck} onChange={(event) => setWeakAck(event.target.checked)} />{t('weakPasswordAck')}</label>}<button className="primary" disabled={busy} onClick={() => void changeMaster()}>{t('changeMaster')}</button>{security?.recovery_enabled ? <><button className="secondary" disabled={busy} onClick={() => void recoveryAction('rotate')}>{t('rotateRecovery')}</button><button className="danger-outline" disabled={busy} onClick={() => void recoveryAction('disable')}>{t('disableRecovery')}</button></> : <button className="secondary" disabled={busy} onClick={() => void recoveryAction('enable')}>{t('enableRecovery')}</button>}<label>{t('resetPhrase')}<input value={resetPhrase} onChange={(event) => setResetPhrase(event.target.value)} /></label><button className="danger-outline" disabled={busy} onClick={() => void reset()}>{t('resetVault')}</button></div></section>}
    {section === 'host' && host && <section className="card setting-section"><div className="card-title"><h2>{t('hostNetwork')}</h2></div><div className="setting-row"><strong>{t('port')}</strong><input type="number" min="1024" max="65535" value={host.port} onChange={(event) => setHost({ ...host, port: Number(event.target.value) })} /></div><div className="setting-row"><strong>{t('autostart')}</strong><input type="checkbox" checked={host.autostart} onChange={(event) => setHost({ ...host, autostart: event.target.checked })} /></div><div className="setting-row"><span>0.0.0.0 · {t('lanDefault')}</span></div><button className="primary save-settings" disabled={busy} onClick={() => void saveHost()}>{t('save')}</button></section>}
    {section === 'backup' && <section className="card setting-section"><div className="card-title"><h2>{t('backup')}</h2></div><button className="primary" onClick={navigateBackup}>{t('openBackup')}</button></section>}
  </div></div></div>
}

function HelpDialog({ t, close }: { t: (key: any) => string; close: () => void }) { return <NativeDialog title={t('help')} close={close}><div className="modal-form"><div className="plaintext-warning"><ShieldAlert /><div><strong>{t('httpBanner')}</strong><span>{t('threatModel')}</span></div></div><h3>{t('shortcuts')}</h3><p><kbd>/</kbd> {t('focusSearch')}</p><p><kbd>Ctrl/Cmd+N</kbd> {t('newCredential')}</p><p><kbd>Ctrl/Cmd+K</kbd> {t('openHelp')}</p><p><kbd>?</kbd> {t('help')}</p><div className="modal-actions"><button className="primary" onClick={close}>{t('close')}</button></div></div></NativeDialog> }
