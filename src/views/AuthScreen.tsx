import { useState, type FormEvent } from 'react'
import { Check, Database, HardDrive, KeyRound, LockKeyhole, RefreshCw, ShieldAlert, ShieldCheck, Wifi } from 'lucide-react'
import { api, type Lang, type SessionResult } from '../api'
import { errorText, strengthOf } from '../utils/helpers'
import type { Screen } from '../types'
import { SignupScreen } from './SignupScreen'

export function AuthScreen({ screen, setupRequired, activeHost, lang, setLang, t, onSuccess, onScreen, retry }: { screen: Screen; setupRequired: boolean; activeHost?: string; lang: Lang; setLang: (lang: Lang) => void; t: (key: any) => string; onSuccess: (result: SessionResult) => void; onScreen: (screen: Screen) => void; retry: () => void }) {
  const [master, setMaster] = useState('')
  const [login, setLogin] = useState('')
  const [confirmation, setConfirmation] = useState('')
  const [recovery, setRecovery] = useState('')
  const [weakAck, setWeakAck] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  
  if (screen === 'boot') return <div className="auth-page loading-state"><RefreshCw className="spin" /><p>{t('loading')}</p></div>
  if (screen === 'offline') return <div className="auth-page loading-state"><ShieldAlert /><h1>{t('serverUnavailable')}</h1><button className="primary" onClick={retry}>{t('retry')}</button></div>
  if (screen === 'signup') return <SignupScreen activeHost={activeHost} lang={lang} setLang={setLang} t={t} onSuccess={onSuccess} onScreen={onScreen} />
  
  const isLogin = screen === 'login'
  const isRecover = screen === 'recover'
  const strength = strengthOf(master)
  
  async function submit(event: FormEvent): Promise<void> {
    event.preventDefault(); setBusy(true); setError('')
    try {
      if (isLogin) onSuccess(await api.login(login, master))
      else if (isRecover) onSuccess(await api.recover({ recovery_key: recovery, new_master_password: master, confirm_new_master_password: confirmation, weak_password_acknowledged: weakAck }))
    } catch (reason) { setError(errorText(reason)) }
    finally { setBusy(false) }
  }
  
  return (
    <div className="auth-page">
      <header className="auth-header">
        <div className="brand auth-brand"><span className="brand-mark"><LockKeyhole size={20} /></span>{t('appName')}</div>
        <div className="auth-header-actions"><label className="language-switcher"><span className="sr-only">{t('language')}</span><select value={lang} onChange={(event) => setLang(event.target.value as Lang)} aria-label={t('language')}><option value="id">ID</option><option value="en">EN</option></select></label><div className="auth-connection"><Wifi size={16} /><span>{t('lanActive')}</span><strong>{activeHost || window.location.host}</strong></div></div>
      </header>
      <main className="auth-layout">
        <section className="auth-intro">
          <p className="auth-kicker">{t('privateNoCloud')}</p>
          <h1>{isRecover ? t('recover') : t('loginWelcome')}</h1>
          {!isRecover && <p className="auth-lead">{t('loginLead')}</p>}
          {!isRecover && <>
            <div className="auth-vault-visual"><span className="auth-vault-ring"><LockKeyhole size={28} /></span><div><strong>{setupRequired ? t('vaultNotFound') : t('vaultFound')}</strong><span>{setupRequired ? t('firstSetupNeeded') : `${t('revision')} 184 · ${t('recoveryActive')}`}</span></div><Check size={18} /></div>
            <div className="auth-points">
              <div><span><HardDrive size={18} /></span><p><strong>{t('savedLocally')}</strong><small>{t('savedLocallySub')}</small></p></div>
              <div><span><ShieldCheck size={18} /></span><p><strong>{t('singleMasterPassword')}</strong><small>{t('singleMasterPasswordSub')}</small></p></div>
              <div><span><KeyRound size={18} /></span><p><strong>{t('optionalRecovery')}</strong><small>{t('optionalRecoverySub')}</small></p></div>
            </div>
          </>}
        </section>
        <section className="auth-card">
          <div className="auth-card-heading"><span className="auth-mode-badge">{isRecover ? t('recover') : t('loginBadge')}</span><h2>{isRecover ? t('recover') : t('loginCardTitle')}</h2><p>{isRecover ? t('recoveryKey') : t('loginSubtitle')}</p></div>
          {!isRecover && <div className="auth-vault-status"><span><Database size={18} /></span><div><strong>{setupRequired ? t('firstSetup') : t('vaultFound')}</strong><small>{setupRequired ? t('firstSetupNeeded') : `${t('revision')} 184 · ${t('recoveryActive')}`}</small></div><Check className="status-check" size={18} /></div>}
          <form className="auth-form" onSubmit={(event) => void submit(event)}>
            {isRecover && <label><span>{t('recoveryKey')}</span><div className="auth-input"><KeyRound size={18} /><input required value={recovery} onChange={(event) => setRecovery(event.target.value)} /></div></label>}
            {isLogin && <label><span>{t('usernameOrEmail')}</span><div className="auth-input"><KeyRound size={18} /><input required autoComplete="username" value={login} onChange={(event) => setLogin(event.target.value)} /></div></label>}
            <label><span>{isRecover ? t('newMaster') : t('masterPassword')}</span><div className="auth-input"><LockKeyhole size={18} /><input type="password" required value={master} onChange={(event) => setMaster(event.target.value)} /></div></label>
            {!isLogin && (
              <>
                <label><span>{t('confirmMaster')}</span><div className="auth-input"><ShieldCheck size={18} /><input type="password" required value={confirmation} onChange={(event) => setConfirmation(event.target.value)} /></div></label>
                <div className="strength-row"><span>{t('passwordStrength')}</span><strong>{t(strength)}</strong></div>
                {strength === 'weak' && <label className="auth-check"><input type="checkbox" checked={weakAck} onChange={(event) => setWeakAck(event.target.checked)} /><span>{t('weakPasswordAck')}</span></label>}
              </>
            )}
            {isLogin && <div className="auth-form-options"><label className="auth-inline-check"><input type="checkbox" />{t('rememberTabConnected')}</label><button type="button" className="auth-recovery-link" onClick={() => onScreen('recover')}><KeyRound size={15} />{t('useRecovery')}</button></div>}
            <button className="auth-submit" disabled={busy || (!isLogin && strength === 'weak' && !weakAck)}><LockKeyhole size={16} />{busy ? t('working') : isLogin ? t('openVault') : t('recover')}</button>
          </form>
          {error && <p className="form-error">{error}</p>}
          <div className="auth-card-footer"><p className="auth-switch-text"><span>{setupRequired ? t('notConfiguredYet') : t('alreadyConfigured')}</span>{setupRequired ? <button type="button" className="link-action" onClick={() => onScreen('signup')}>{t('createFirstAccount')} ›</button> : <button type="button" className="link-action" onClick={() => onScreen('recover')}>{t('useRecovery')}</button>}</p><div className="auth-security-notice"><ShieldAlert className="notice-icon" size={17} /><div><strong>{t('noLoginThrottleTitle')}</strong><p>{t('noLoginThrottleText')}</p></div></div></div>
          {isRecover && <button type="button" className="link-button" onClick={() => onScreen('login')}>{t('switchToLogin')}</button>}
        </section>
      </main>
    </div>
  )
}
