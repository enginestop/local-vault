import type { ReactNode } from 'react'

export function Field({ label, value, action }: { label: string; value: string; action: ReactNode }) { 
  return (
    <div className="field">
      <label>{label}</label>
      <div className="field-box"><span>{value}</span><div>{action}</div></div>
    </div>
  ) 
}
