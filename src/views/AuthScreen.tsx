import { useState, type FormEvent } from 'react'
import { KeyRound, LockKeyhole, RefreshCw, ShieldAlert, ShieldCheck, Wifi } from 'lucide-react'
import { api, type Lang, type SessionResult } from '../api'
import { errorText, strengthOf } from '../utils/helpers'
import type { Screen } from '../types'
import { SignupScreen } from './SignupScreen'

export function AuthScreen({ screen, lang, setLang, t, onSuccess, onScreen, retry }: { screen: Screen; lang: Lang; setLang: (lang: Lang) => void; t: (key: any) => string; onSuccess: (result: SessionResult) => void; onScreen: (screen: Screen) => void; retry: () => void }) {
  const [master, setMaster] = useState('')
  const [confirmation, setConfirmation] = useState('')
  const [recovery, setRecovery] = useState('')
  const [weakAck, setWeakAck] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  
  if (screen === 'boot') return <div className="auth-page loading-state"><RefreshCw className="spin" /><p>{t('loading')}</p></div>
  if (screen === 'offline') return <div className="auth-page loading-state"><ShieldAlert /><h1>{t('serverUnavailable')}</h1><button className="primary" onClick={retry}>{t('retry')}</button></div>
  if (screen === 'signup') return <SignupScreen lang={lang} setLang={setLang} t={t} onSuccess={onSuccess} onScreen={onScreen} />
  
  const isLogin = screen === 'login'
  const isRecover = screen === 'recover'
  const strength = strengthOf(master)
  
  async function submit(event: FormEvent): Promise<void> {
    event.preventDefault(); setBusy(true); setError('')
    try {
      if (isLogin) onSuccess(await api.unlock(master))
      else if (isRecover) onSuccess(await api.recover({ recovery_key: recovery, new_master_password: master, confirm_new_master_password: confirmation, weak_password_acknowledged: weakAck }))
    } catch (reason) { setError(errorText(reason)) }
    finally { setBusy(false) }
  }
  
  return (
    <div className="auth-page">
      <div className="http-banner auth-banner"><ShieldAlert size={16} /><strong>{t('httpBanner')}</strong></div>
      <header className="auth-header">
        <div className="brand auth-brand"><span className="brand-mark"><LockKeyhole size={20} /></span>{t('appName')}</div>
        <div className="auth-connection"><Wifi size={16} />{t('lanActive')}</div>
      </header>
      <main className="auth-layout">
        <section className="auth-intro">
          <p className="auth-kicker">{t('privateNoCloud')}</p>
          <h1>{isRecover ? t('recover') : t('loginTitle')}</h1>
        </section>
        <section className="auth-card">
          <form className="auth-form" onSubmit={(event) => void submit(event)}>
            {isRecover && <label><span>{t('recoveryKey')}</span><div className="auth-input"><KeyRound size={18} /><input required value={recovery} onChange={(event) => setRecovery(event.target.value)} /></div></label>}
            <label><span>{isRecover ? t('newMaster') : t('masterPassword')}</span><div className="auth-input"><LockKeyhole size={18} /><input type="password" required value={master} onChange={(event) => setMaster(event.target.value)} /></div></label>
            {!isLogin && (
              <>
                <label><span>{t('confirmMaster')}</span><div className="auth-input"><ShieldCheck size={18} /><input type="password" required value={confirmation} onChange={(event) => setConfirmation(event.target.value)} /></div></label>
                <div className="strength-row"><span>{t('passwordStrength')}</span><strong>{t(strength)}</strong></div>
                {strength === 'weak' && <label className="auth-check"><input type="checkbox" checked={weakAck} onChange={(event) => setWeakAck(event.target.checked)} /><span>{t('weakPasswordAck')}</span></label>}
              </>
            )}
            {error && <p className="form-error">{error}</p>}
            <button className="primary auth-submit" disabled={busy || (!isLogin && strength === 'weak' && !weakAck)}>{busy ? t('working') : isLogin ? t('openVault') : t('recover')}</button>
          </form>
          {isLogin && <button className="link-button" onClick={() => onScreen('recover')}>{t('useRecovery')}</button>}
          {isRecover && <button className="link-button" onClick={() => onScreen('login')}>{t('switchToLogin')}</button>}
          <div className="auth-switch"><button type="button" onClick={retry}>{t('retry')}</button></div>
        </section>
      </main>
    </div>
  )
}
