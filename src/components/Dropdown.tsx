import { useEffect, useRef, useState, type ReactNode } from 'react'
import { Check, ChevronDown } from 'lucide-react'

export type DropdownOption = { value: string; label: ReactNode }

export function Dropdown({ value, options, onChange, ariaLabel, name, className = '', disabled = false }: {
  value: string
  options: DropdownOption[]
  onChange: (value: string) => void
  ariaLabel?: string
  name?: string
  className?: string
  disabled?: boolean
}) {
  const [open, setOpen] = useState(false)
  const rootRef = useRef<HTMLDivElement>(null)
  const selected = options.find((option) => option.value === value)

  useEffect(() => {
    function close(event: MouseEvent): void {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false)
    }
    function closeOnEscape(event: KeyboardEvent): void {
      if (event.key === 'Escape') setOpen(false)
    }
    document.addEventListener('mousedown', close)
    document.addEventListener('keydown', closeOnEscape)
    return () => {
      document.removeEventListener('mousedown', close)
      document.removeEventListener('keydown', closeOnEscape)
    }
  }, [])

  return <div className={`dropdown ${className}`} ref={rootRef}>
    {name && <input type="hidden" name={name} value={value} />}
    <button type="button" className="dropdown-trigger" aria-haspopup="listbox" aria-expanded={open} aria-label={ariaLabel} disabled={disabled} onClick={() => setOpen((current) => !current)}>
      <span>{selected?.label || ''}</span><ChevronDown size={14} aria-hidden="true" />
    </button>
    {open && <div className="dropdown-menu" role="listbox" aria-label={ariaLabel}>
      {options.map((option) => <button type="button" role="option" aria-selected={option.value === value} className={`dropdown-option ${option.value === value ? 'selected' : ''}`} key={option.value} onClick={() => { onChange(option.value); setOpen(false) }}>
        <span>{option.label}</span>{option.value === value && <Check size={14} aria-hidden="true" />}
      </button>)}
    </div>}
  </div>
}
