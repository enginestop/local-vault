export const API_BASE: string = (import.meta as any).env?.VITE_API_BASE || ''

export type Lang = 'id' | 'en'

export interface PasswordHistoryEntry {
  id: string
  password: string
  changed_at: string
}

export interface CustomField {
  id?: string
  label: string
  type: 'text' | 'secret'
  value: string
  order?: number
}

export interface Credential {
  id: string
  name: string
  username: string | null
  url: string | null
  password: string
  category_id: string | null
  tags: string[]
  favorite: boolean
  notes: string
  custom_fields: CustomField[]
  password_history: PasswordHistoryEntry[]
  created_at: string
  updated_at: string
  deleted_at: string | null
  revision: number
}

export interface Category {
  id: string
  name: string
  revision: number
  created_at?: string
  updated_at?: string
}

export interface VaultSettings {
  language: Lang
  tag_filter_mode: 'and' | 'or'
  default_sort: { field: string; direction: string }
  page_size: 25 | 50 | 100
  warning_acknowledgements: string[]
}

export interface SecurityStatus {
  kdf_algorithm: string
  kdf_m_cost_kib: number
  kdf_t_cost: number
  kdf_parallelism: number
  recovery_enabled: boolean
}

export interface BackupItem {
  backup_id: string
  vault_id: string
  schema_version: number
  vault_revision: number
  created_at: string
  kind: string
  operation: string | null
  envelope_sha256: string
  application_version: string
  relative_path: string
  bucket: string
  valid: number
}

export interface SessionResult {
  token: string
  session_id: string
  user_id?: string
  username?: string
  email?: string
  recovery_key?: string | null
}

export interface UserProfile {
  id: string
  username: string
  email: string
  display_name: string
  recovery_enabled: boolean
  created_at: string
}

export interface ImportPreview {
  id: string
  profile: string
  delimiter: string
  mapping: Record<string, unknown>
  source_columns: string[]
  valid_count: number
  invalid_count: number
  conflict_count: number
  warnings: string[]
  sample: Array<Record<string, any>>
  invalid_sample: Array<Record<string, any>>
  conflicts: Array<Record<string, any>>
}

export interface ExportResult {
  blob: Blob
  filename: string
}

export interface StatusResult {
  setup_required: boolean
  application_version: string
  api_version: string
  schema_version: number
  port: number
  locked?: boolean
  recovery_enabled?: boolean
  http_lan_warning?: boolean
  network_host?: string
}

const TOKEN_KEY = 'lv_token'
const TAB_KEY = 'lv_tab_id'

let _currentUser: { username: string; email: string } | null = null

export function getCurrentUser() { return _currentUser }
export function setCurrentUser(user: { username: string; email: string } | null) { _currentUser = user }

export function getToken(): string | null {
  return sessionStorage.getItem(TOKEN_KEY)
}

export function setToken(value: string | null): void {
  if (value) sessionStorage.setItem(TOKEN_KEY, value)
  else sessionStorage.removeItem(TOKEN_KEY)
}

export function getTabId(): string {
  let value = sessionStorage.getItem(TAB_KEY)
  if (!value) {
    value = crypto.randomUUID()
    sessionStorage.setItem(TAB_KEY, value)
  }
  return value
}

export function resetTabId(): string {
  const value = crypto.randomUUID()
  sessionStorage.setItem(TAB_KEY, value)
  return value
}

export function authHeaders(extra: Record<string, string> = {}): Record<string, string> {
  const currentToken = getToken()
  return currentToken
    ? { Authorization: `Bearer ${currentToken}`, 'X-Tab-Instance-ID': getTabId(), ...extra }
    : { ...extra }
}

export class ApiError extends Error {
  status: number
  code: string
  detail: string
  requestId?: string

  constructor(status: number, code: string, detail: string, requestId?: string) {
    super(detail)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.detail = detail
    this.requestId = requestId
  }
}

function safeMessage(value: unknown, fallback: string): string {
  if (typeof value === 'string' && value.trim()) return value
  if (Array.isArray(value)) {
    const messages = value.map((entry) => {
      if (typeof entry === 'string') return entry
      if (entry && typeof entry === 'object') {
        const item = entry as Record<string, unknown>
        const location = Array.isArray(item.loc) ? item.loc.join('.') : ''
        const message = typeof item.msg === 'string' ? item.msg : ''
        return [location, message].filter(Boolean).join(': ')
      }
      return ''
    }).filter(Boolean)
    if (messages.length) return messages.join('; ')
  }
  if (value && typeof value === 'object') {
    const item = value as Record<string, unknown>
    return safeMessage(item.message || item.msg, fallback)
  }
  return fallback || 'Request failed'
}

async function parseResponse(response: Response): Promise<any> {
  if (response.status === 204) return undefined
  const text = await response.text()
  if (!text) return undefined
  try { return JSON.parse(text) } catch { return text }
}

function notifySessionEnded(code: string): void {
  setToken(null)
  _currentUser = null
  window.dispatchEvent(new CustomEvent('localvault:session-ended', { detail: { code } }))
}

async function request<T>(
  method: string,
  path: string,
  options: { body?: unknown; headers?: Record<string, string>; isForm?: boolean } = {},
): Promise<T> {
  const headers = authHeaders(options.headers || {})
  let body: BodyInit | undefined
  if (options.body !== undefined) {
    if (options.isForm) body = options.body as FormData
    else {
      body = JSON.stringify(options.body)
      headers['Content-Type'] = 'application/json'
    }
  }
  let response: Response
  try {
    response = await fetch(`${API_BASE}${path}`, { method, headers, body, cache: 'no-store' })
  } catch (error) {
    throw new ApiError(0, 'NETWORK_ERROR', error instanceof Error ? error.message : 'Server is unreachable')
  }
  const data = await parseResponse(response)
  if (!response.ok) {
    const problem = data && typeof data === 'object' ? data as Record<string, unknown> : {}
    const code = typeof problem.code === 'string' ? problem.code : `HTTP_${response.status}`
    const detail = safeMessage(problem.detail, safeMessage(data, response.statusText))
    if (code === 'SESSION_INVALID' || code === 'VAULT_LOCKED') notifySessionEnded(code)
    throw new ApiError(response.status, code, detail, typeof problem.request_id === 'string' ? problem.request_id : undefined)
  }
  return data as T
}

function appendQuery(params: Record<string, string | number | boolean | string[]>): string {
  const query = new URLSearchParams()
  Object.entries(params).forEach(([key, value]) => {
    if (Array.isArray(value)) value.forEach((item) => query.append(key, item))
    else query.set(key, String(value))
  })
  return query.toString()
}

function dispositionFilename(response: Response, fallback: string): string {
  const value = response.headers.get('Content-Disposition') || ''
  const encoded = value.match(/filename\*=UTF-8''([^;]+)/i)?.[1]
  const plain = value.match(/filename="?([^";]+)"?/i)?.[1]
  try { return decodeURIComponent(encoded || plain || fallback) } catch { return plain || fallback }
}

async function downloadRequest(method: string, path: string, body?: unknown): Promise<ExportResult> {
  const headers = authHeaders()
  let requestBody: BodyInit | undefined
  if (body instanceof FormData) requestBody = body
  else if (body !== undefined) {
    headers['Content-Type'] = 'application/json'
    requestBody = JSON.stringify(body)
  }
  let response: Response
  try {
    response = await fetch(`${API_BASE}${path}`, { method, headers, body: requestBody, cache: 'no-store' })
  } catch (error) {
    throw new ApiError(0, 'NETWORK_ERROR', error instanceof Error ? error.message : 'Server is unreachable')
  }
  if (!response.ok) {
    const data = await parseResponse(response)
    const problem = data && typeof data === 'object' ? data as Record<string, unknown> : {}
    const code = typeof problem.code === 'string' ? problem.code : `HTTP_${response.status}`
    if (code === 'SESSION_INVALID' || code === 'VAULT_LOCKED') notifySessionEnded(code)
    throw new ApiError(response.status, code, safeMessage(problem.detail, response.statusText))
  }
  return { blob: await response.blob(), filename: dispositionFilename(response, 'localvault-download') }
}

export const api = {
  status: () => request<StatusResult>('GET', '/api/v1/status'),

  setup: (payload: Record<string, unknown>) =>
    request<SessionResult>('POST', '/api/v1/setup', { body: { ...payload, tab_instance_id: getTabId() } }),

  register: (payload: Record<string, unknown>) => request<SessionResult>('POST', '/api/v1/register', { body: { ...payload, tab_instance_id: getTabId() } }),

  login: (login: string, master_password: string) =>
    request<SessionResult>('POST', '/api/v1/sessions/login', { body: { login, master_password, tab_instance_id: getTabId() } }),

  unlock: (master_password: string) =>
    request<SessionResult>('POST', '/api/v1/sessions/unlock', { body: { master_password, tab_instance_id: getTabId() } }),

  recover: (payload: Record<string, unknown>) =>
    request<SessionResult>('POST', '/api/v1/sessions/recover', { body: { ...payload, tab_instance_id: getTabId() } }),

  logout: () => request<void>('POST', '/api/v1/sessions/logout'),

  current: () => request<{ session_id: string; user_id: string; username: string; email: string; client_label: string }>('GET', '/api/v1/sessions/current'),

  lock: () => request<void>('POST', '/api/v1/sessions/lock'),
  lockAll: () => request<void>('POST', '/api/v1/sessions/lock-all'),
  eventTicket: () => request<{ ticket: string }>('POST', '/api/v1/sessions/event-ticket'),

  getProfile: () => request<UserProfile>('GET', '/api/v1/users/me'),
  updateProfile: (body: Record<string, unknown>) => request<UserProfile>('PUT', '/api/v1/users/me', { body }),

  listCredentials: (params: Record<string, string | number | boolean | string[]> = {}) =>
    request<{ items: Credential[]; page: number; page_size: number; total: number; vault_revision: number }>('GET', `/api/v1/credentials?${appendQuery(params)}`),
  getCredential: (id: string) => request<Credential>('GET', `/api/v1/credentials/${id}`),
  createCredential: (body: Record<string, unknown>) => request<Credential>('POST', '/api/v1/credentials', { body }),
  updateCredential: (id: string, body: any, revision: number, overwrite = false) =>
    request<Credential>('PUT', `/api/v1/credentials/${id}`, { body: { ...body, base_revision: revision, ...(overwrite ? { conflict_resolution: 'overwrite' } : {}) }, headers: { 'If-Match': `"${revision}"` } }),
  trashCredential: (id: string, revision: number) => request('POST', `/api/v1/credentials/${id}/trash`, { headers: { 'If-Match': `"${revision}"` } }),
  restoreCredential: (id: string, revision: number) => request('POST', `/api/v1/credentials/${id}/restore`, { headers: { 'If-Match': `"${revision}"` } }),
  purgeCredential: (id: string, revision: number) => request('DELETE', `/api/v1/credentials/${id}`, { headers: { 'If-Match': `"${revision}"` } }),
  bulk: (action: string, credentials: Credential[], argumentsValue: Record<string, unknown> = {}) =>
    request<{ applied: boolean; count: number; vault_revision: number }>('POST', '/api/v1/credentials/bulk', { body: { action, ids: credentials.map(({ id, revision }) => ({ id, revision })), arguments: argumentsValue } }),
  emptyTrash: (count_expected: number) => request('POST', '/api/v1/trash/empty', { body: { confirmation: true, count_expected } }),

  categories: () => request<{ items: Category[]; vault_revision: number }>('GET', '/api/v1/categories'),
  createCategory: (name: string) => request<Category>('POST', '/api/v1/categories', { body: { name } }),
  updateCategory: (id: string, name: string, revision: number) => request<Category>('PUT', `/api/v1/categories/${id}`, { body: { name }, headers: { 'If-Match': `"${revision}"` } }),
  deleteCategory: (id: string, revision: number) => request('DELETE', `/api/v1/categories/${id}`, { headers: { 'If-Match': `"${revision}"` } }),
  tags: () => request<{ items: string[]; vault_revision: number }>('GET', '/api/v1/tags'),
  createTag: (name: string) => request('POST', '/api/v1/tags', { body: { name } }),
  renameTag: (source: string, target: string, vaultRevision: number) => request('POST', '/api/v1/tags/rename', { body: { source, target }, headers: { 'X-Vault-Revision': String(vaultRevision) } }),
  deleteTag: (name: string, vaultRevision: number) => request('DELETE', `/api/v1/tags/${encodeURIComponent(name)}`, { headers: { 'X-Vault-Revision': String(vaultRevision) } }),

  generate: (body: Record<string, unknown>) => request<{ password: string; strength: 'weak' | 'good' | 'strong' }>('POST', '/api/v1/password-generator', { body }),
  security: () => request<SecurityStatus>('GET', '/api/v1/settings/security'),
  general: () => request<VaultSettings>('GET', '/api/v1/settings/general'),
  updateGeneral: (body: Record<string, unknown>) => request<VaultSettings>('PUT', '/api/v1/settings/general', { body }),
  host: () => request<{ port: number; autostart: boolean; restart_required: boolean; lan_access_enabled: boolean; bind_host: string }>('GET', '/api/v1/settings/host'),
  updateHost: (body: { port?: number; autostart?: boolean }) => request<{ port: number; autostart: boolean; restart_required: boolean }>('PUT', '/api/v1/settings/host', { body }),
  recoveryAction: (action: 'enable' | 'rotate', current_master_password: string) =>
    request<{ recovery_key: string | null; enabled: boolean }>('POST', '/api/v1/settings/security/recovery-key', { body: { action, current_master_password } }),
  disableRecovery: (current_master_password: string) => request<void>('DELETE', '/api/v1/settings/security/recovery-key', { body: { current_master_password } }),
  changeMaster: (body: Record<string, unknown>) => request('PUT', '/api/v1/settings/security/master-password', { body }),
  resetVault: (body: Record<string, unknown>) => request<{ reset: boolean; recovery_key?: string }>('POST', '/api/v1/settings/security/reset-vault', { body }),

  backups: () => request<{ items: BackupItem[]; vault_revision: number }>('GET', '/api/v1/backups'),
  manualBackup: () => request<BackupItem>('POST', '/api/v1/backups/manual'),
  downloadBackup: (id: string) => downloadRequest('GET', `/api/v1/backups/${id}/download`),
  restoreBackup: (input: { backupId?: string; file?: File; masterPassword?: string; recoveryKey?: string }) => {
    const form = new FormData()
    if (input.backupId) form.append('backup_id', input.backupId)
    if (input.file) form.append('file', input.file)
    if (input.masterPassword) form.append('master_password', input.masterPassword)
    if (input.recoveryKey) form.append('recovery_key', input.recoveryKey)
    return request<{ restored: boolean }>('POST', '/api/v1/backups/restore', { isForm: true, body: form })
  },

  exportVault: (body: Record<string, unknown>) => downloadRequest('POST', '/api/v1/exports', body),
  importPreview: (file: File, profile: string, delimiter: string | null, mapping: Record<string, unknown> = {}) => {
    const form = new FormData()
    form.append('file', file)
    form.append('profile', profile)
    if (delimiter) form.append('delimiter', delimiter)
    form.append('mapping', JSON.stringify(mapping))
    return request<ImportPreview>('POST', '/api/v1/imports/previews', { isForm: true, body: form })
  },
  updateImport: (id: string, body: { mapping?: Record<string, unknown>; resolutions?: Array<{ row_number: number; resolution: string }> }) =>
    request<ImportPreview>('PUT', `/api/v1/imports/previews/${id}`, { body }),
  commitImport: (id: string) => request<{ committed: number; rows: number[] }>('POST', `/api/v1/imports/previews/${id}/commit`),
  cancelImport: (id: string) => request('DELETE', `/api/v1/imports/previews/${id}`),
  downloadImportErrors: (id: string) => downloadRequest('GET', `/api/v1/imports/previews/${id}/errors.csv`),
}

export function websocketUrl(ticket: string): string {
  const base = API_BASE || window.location.origin
  const url = new URL('/api/v1/events', base)
  url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:'
  url.searchParams.set('ticket', ticket)
  return url.toString()
}

export function saveBlob(result: ExportResult): void {
  const url = URL.createObjectURL(result.blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = result.filename
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  window.setTimeout(() => URL.revokeObjectURL(url), 0)
}
