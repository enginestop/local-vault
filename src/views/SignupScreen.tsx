import { useState, type FormEvent } from 'react'
import { LockKeyhole, ShieldCheck, KeyRound, HardDrive, Eye, EyeOff, Globe, Wifi } from 'lucide-react'
import { api, ApiError, type Lang, type SessionResult } from '../api'
import { errorText, strengthOf } from '../utils/helpers'
import './SignupScreen.css'
import type { Screen } from '../types'

export function SignupScreen({ activeHost, lang, setLang, t, onSuccess, onScreen }: { activeHost?: string; lang: Lang; setLang: (lang: Lang) => void; t: (key: any) => string; onSuccess: (result: SessionResult) => void; onScreen: (screen: Screen) => void }) {
  const [master, setMaster] = useState('')
  const [username, setUsername] = useState('')
  const [email, setEmail] = useState('')
  const [confirmation, setConfirmation] = useState('')
  const [createRecovery, setCreateRecovery] = useState(true)
  const [riskAck, setRiskAck] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [showMaster, setShowMaster] = useState(false)
  const [showConfirm, setShowConfirm] = useState(false)
  const [weakAck, setWeakAck] = useState(false)
  
  const strength = strengthOf(master)
  
  async function submit(event: FormEvent): Promise<void> {
    event.preventDefault(); 
    if (master !== confirmation) {
      setError(t('masterMismatch') || 'Passwords do not match')
      return
    }
    
    setBusy(true); 
    setError('')
    try {
      onSuccess(await api.register({
        username,
        email,
        master_password: master, 
        confirm_master_password: confirmation, 
        create_recovery_key: createRecovery, 
        language: lang, 
        weak_password_acknowledged: weakAck,
        http_lan_risk_acknowledged: riskAck 
      }))
    } catch (reason) {
      const accountExists = reason instanceof ApiError && ['USERNAME_TAKEN', 'EMAIL_TAKEN', 'SETUP_ALREADY_COMPLETED'].includes(reason.code)
      setError(accountExists ? t('accountAlreadyExists') : errorText(reason))
    } finally { 
      setBusy(false) 
    }
  }

  const isSubmitDisabled = busy || !username.trim() || !email.trim() || (!master) || (master !== confirmation) || (strength === 'weak' && !weakAck) || !riskAck
  
  return (
    <div className="signup-page">
      <header className="signup-header">
        <div className="signup-brand">
          <div className="signup-brand-icon"><LockKeyhole size={18} /></div>
          LocalVault
        </div>
        <div className="signup-connection">
          <label className="signup-language-switcher"><span className="sr-only">{t('language')}</span><select value={lang} onChange={(event) => setLang(event.target.value as Lang)} aria-label={t('language')}><option value="id">ID</option><option value="en">EN</option></select></label><Wifi size={14} /> {t('lanActive')} <span>{activeHost || window.location.host}</span>
        </div>
      </header>

      <div className="signup-container">
        {/* Left Column */}
        <div className="signup-left">
          
          <div className="signup-badge">
            {t('signupBadge')}
          </div>
          
          <h1 className="signup-hero">
            {t('signupHeroLine1')}<br />{t('signupHeroLine2')}
          </h1>
          
          <p className="signup-description">
            {t('signupDescription')}
          </p>
          
          <div className="signup-highlight">
            <div className="signup-highlight-icon">
              <LockKeyhole size={24} />
            </div>
            <div className="signup-highlight-content">
              <h3>AES-256-GCM</h3>
              <p>{t('dataEncryptedAtRest')}</p>
            </div>
          </div>
          
          <div className="signup-features">
            <div className="signup-feature-item">
              <div className="signup-feature-icon">
                <HardDrive size={18} />
              </div>
              <div className="signup-feature-text">
                <h4>{t('savedLocally')}</h4>
                <p>{t('savedLocallySub')}</p>
              </div>
            </div>
            <div className="signup-feature-item">
              <div className="signup-feature-icon">
                <ShieldCheck size={18} />
              </div>
              <div className="signup-feature-text">
                <h4>{t('singleMasterPassword')}</h4>
                <p>{t('singleMasterPasswordSub')}</p>
              </div>
            </div>
            <div className="signup-feature-item">
              <div className="signup-feature-icon">
                <KeyRound size={18} />
              </div>
              <div className="signup-feature-text">
                <h4>{t('optionalRecovery')}</h4>
                <p>{t('optionalRecoverySub')}</p>
              </div>
            </div>
          </div>
        </div>

        {/* Right Column */}
        <div className="signup-right">
          <div className="signup-card">
            <span className="signup-card-badge">{t('signupCardBadge')}</span>
            <h2 className="signup-card-title">{t('signupCardTitle')}</h2>
            <p className="signup-card-subtitle">{t('signupCardSubtitle')}</p>
            
            <form className="signup-form" onSubmit={(event) => void submit(event)}>
              <div className="signup-form-group">
                <label className="signup-label" htmlFor="signup-username">{t('usernameLabel')}</label>
                <div className="signup-input-wrapper">
                  <KeyRound size={18} className="signup-input-icon-left" />
                  <input id="signup-username" required autoComplete="username" className="signup-input" value={username} onChange={(event) => setUsername(event.target.value)} placeholder={t('usernamePlaceholder')} />
                </div>
              </div>

              <div className="signup-form-group">
                <label className="signup-label" htmlFor="signup-email">{t('emailLabel')}</label>
                <div className="signup-input-wrapper">
                  <Globe size={18} className="signup-input-icon-left" />
                  <input id="signup-email" required type="email" autoComplete="email" className="signup-input" value={email} onChange={(event) => setEmail(event.target.value)} placeholder={t('emailPlaceholder')} />
                </div>
              </div>
              
              <div className="signup-form-group">
                <label className="signup-label" htmlFor="signup-master">{t('masterPassword')}</label>
                <div className="signup-input-wrapper">
                  <LockKeyhole size={18} className="signup-input-icon-left" />
                  <input 
                    type={showMaster ? 'text' : 'password'} 
                    required 
                    id="signup-master" className="signup-input"
                    value={master} 
                    onChange={(event) => setMaster(event.target.value)} 
                    placeholder={t('masterPasswordPlaceholder')}
                  />
                  <button type="button" className="signup-input-icon-right" onClick={() => setShowMaster(!showMaster)}>
                    {showMaster ? <EyeOff size={18} /> : <Eye size={18} />}
                  </button>
                </div>
              </div>
              
              <div className="signup-form-group">
                <label className="signup-label" htmlFor="signup-confirm">{t('confirmMaster')}</label>
                <div className="signup-input-wrapper">
                  <ShieldCheck size={18} className="signup-input-icon-left" />
                  <input 
                    type={showConfirm ? 'text' : 'password'} 
                    required 
                    id="signup-confirm" className="signup-input"
                    value={confirmation} 
                    onChange={(event) => setConfirmation(event.target.value)} 
                    placeholder={t('confirmMasterPlaceholder')}
                  />
                  <button type="button" className="signup-input-icon-right" onClick={() => setShowConfirm(!showConfirm)}>
                    {showConfirm ? <EyeOff size={18} /> : <Eye size={18} />}
                  </button>
                </div>
              </div>

              <div className="signup-strength-container">
                <div className="signup-strength-header">
                  <span className="signup-strength-label">{t('passwordStrength')}</span>
                  <span className={`signup-strength-text signup-strength-text-${strength}`}>
                    {master ? t(strength) : ''}
                  </span>
                </div>
                <div className={`signup-strength-indicator signup-strength-${master ? strength : 'none'}`}>
                  <div className="signup-strength-bar"></div>
                  <div className="signup-strength-bar"></div>
                  <div className="signup-strength-bar"></div>
                  <div className="signup-strength-bar"></div>
                </div>
                <p className="signup-strength-hint">{t('passwordStrengthHint')}</p>
              </div>

              {strength === 'weak' && master && (
                <label className="signup-checkbox-group">
                  <input 
                    type="checkbox" 
                    className="signup-checkbox"
                    checked={weakAck} 
                    onChange={(event) => setWeakAck(event.target.checked)} 
                  />
                  <span className="signup-checkbox-label">{t('weakPasswordAck')}</span>
                </label>
              )}
              <label className={`signup-option-card ${createRecovery ? 'active' : ''}`}>
                <input 
                  type="checkbox" 
                  className="signup-checkbox"
                  checked={createRecovery} 
                  onChange={(event) => setCreateRecovery(event.target.checked)} 
                />
                <div className="signup-option-content">
                  <strong>{t('createRecovery')}</strong>
                  <span>{t('recoveryOneTime')}</span>
                </div>
              </label>
              
              <label className={`signup-option-card warning ${riskAck ? 'active' : ''}`}>
                <input 
                  type="checkbox" 
                  required 
                  className="signup-checkbox warning-check"
                  checked={riskAck} 
                  onChange={(event) => setRiskAck(event.target.checked)} 
                />
                <div className="signup-option-content">
                  <strong>{t('httpRiskAckTitle')}</strong>
                  <span>{t('httpRiskAckDetail')}</span>
                </div>
              </label>

              {error && <div className="signup-error">{error}</div>}
              
              <button 
                type="submit" 
                className="signup-submit" 
                disabled={isSubmitDisabled}
              >
                <ShieldCheck size={18} />
                {busy ? t('working') : t('createOpen')}
              </button>
            </form>

            <div className="signup-footer">
              <span className="signup-footer-text">{t('signupFooterText')}</span>
              <button 
                type="button" 
                className="signup-login-link"
                onClick={() => onScreen('login')}
              >
                {t('backToLogin')} &gt;
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
