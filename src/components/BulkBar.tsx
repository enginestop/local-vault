import { useState } from 'react'
import { ArchiveRestore, Folder, Star, Trash2 } from 'lucide-react'
import { api, type Category, type Credential } from '../api'
import { errorText } from '../utils/helpers'
import type { View } from '../types'
import { Dropdown } from './Dropdown'

export function BulkBar({ selectedRows, filtered, credentials, categories, view, t, announce, reload, clear, selectAll }: { selectedRows: string[]; filtered: Credential[]; credentials: Credential[]; categories: Category[]; view: View; t: (key: any) => string; announce: (value: string) => void; reload: () => Promise<void>; clear: () => void; selectAll: () => void }) {
  const [pending, setPending] = useState(false)
  const selected = credentials.filter((item) => selectedRows.includes(item.id))
  
  async function apply(action: string, argumentsValue: Record<string, unknown> = {}): Promise<void> {
    if (pending) return
    if (['trash', 'purge'].includes(action) && !confirm(t('confirmBulk').replace('{count}', String(selected.length)))) return
    setPending(true)
    try { 
      await api.bulk(action, selected, argumentsValue)
      await reload()
      clear()
      announce(t(action === 'set_category' ? 'categoryMoved' : 'bulkUpdated').replace('{count}', String(selected.length)))
    } catch (error) { announce(errorText(error)) } finally { setPending(false) }
  }
  
  const allSelected = filtered.length > 0 && filtered.every((item) => selectedRows.includes(item.id))
  
  return (
    <div className="bulk-bar">
      <strong>{selected.length} {t('selected')}</strong>
      <button onClick={allSelected ? clear : selectAll}>{t('selectAllResults')}</button>
      <div className="bulk-category-control">
        <Folder size={15} aria-hidden="true" />
        <Dropdown value="" options={[{ value: '', label: t('moveToCategory') }, { value: '__none__', label: t('withoutCategory') }, ...categories.map((category) => ({ value: category.id, label: category.name }))]} onChange={(value) => { if (value) void apply('set_category', { category_id: value === '__none__' ? null : value }) }} ariaLabel={t('moveToCategory')} disabled={pending} />
      </div>
      <button onClick={() => void apply('set_favorite')}><Star size={15} /> {t('favorites')}</button>
      {view === 'trash' ? (
        <>
          <button onClick={() => void apply('restore')}><ArchiveRestore size={15} /> {t('recover')}</button>
          <button className="bulk-danger" onClick={() => void apply('purge')}><Trash2 size={15} /> {t('deletePermanent')}</button>
        </>
      ) : (
        <button className="bulk-danger" onClick={() => void apply('trash')}><Trash2 size={15} /> {t('moveTrash')}</button>
      )}
    </div>
  )
}
