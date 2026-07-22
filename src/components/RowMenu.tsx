import { useState } from 'react'
import { MoreHorizontal } from 'lucide-react'
import { api, type Credential } from '../api'
import { errorText } from '../utils/helpers'

export function RowMenu({ item, edit, reload, announce, t }: { item: Credential; edit: () => void; reload: () => Promise<void>; announce: (value: string) => void; t: (key: any) => string }) {
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
  return (
    <details className="row-menu">
      <summary aria-label={t('actions')}><MoreHorizontal size={18} /></summary>
      <div>
        <button onClick={edit}>{t('edit')}</button>
        <button onClick={() => void action('favorite')}>{t('favorites')}</button>
        {item.deleted_at ? (
          <>
            <button onClick={() => void action('restore')}>{t('recover')}</button>
            <button onClick={() => void action('purge')}>{t('deletePermanent')}</button>
          </>
        ) : (
          <button onClick={() => void action('trash')}>{t('moveTrash')}</button>
        )}
      </div>
    </details>
  )
}
