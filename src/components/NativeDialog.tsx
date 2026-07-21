import { useEffect, useRef, type ReactNode } from 'react'
import { X } from 'lucide-react'
import { IconButton } from './IconButton'

export function NativeDialog({ title, close, closeLabel, children, busy = false }: { title: string; close: () => void; closeLabel?: string; children: ReactNode; busy?: boolean }) {
  const ref = useRef<HTMLDialogElement>(null)
  const opener = useRef<HTMLElement | null>(null)
  const accessibleClose = closeLabel || (document.documentElement.lang === 'id' ? 'Tutup' : 'Close')
  
  useEffect(() => {
    opener.current = document.activeElement as HTMLElement | null
    ref.current?.showModal()
    return () => opener.current?.focus()
  }, [])
  
  return (
    <dialog ref={ref} className="modal native-dialog" aria-labelledby="dialog-title" onCancel={(event) => { if (busy) event.preventDefault(); else close() }} onClose={() => !busy && close()}>
      <div className="modal-header">
        <div><p className="eyebrow">LOCALVAULT</p><h2 id="dialog-title">{title}</h2></div>
        <IconButton label={accessibleClose} onClick={() => !busy && close()}><X size={20} /></IconButton>
      </div>
      {children}
    </dialog>
  )
}
