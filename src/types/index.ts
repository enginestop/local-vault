import { Credential } from '../api'

export type Screen = 'boot' | 'app' | 'login' | 'signup' | 'recover' | 'offline'
export type View = 'vault' | 'favorites' | 'trash' | 'backup' | 'settings' | 'admin'
export type Modal =
  | { kind: 'credential'; credential: Credential | null; generator: boolean }
  | { kind: 'export' }
  | { kind: 'import' }
  | { kind: 'help' }
  | null
