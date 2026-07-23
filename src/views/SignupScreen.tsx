import { useState, type FormEvent } from 'react'
import { LockKeyhole, ShieldCheck, KeyRound, HardDrive, ChevronDown, Eye, EyeOff, Globe, Wifi } from 'lucide-react'
import { api, type Lang, type SessionResult } from '../api'
import { errorText, strengthOf } from '../utils/helpers'
import './SignupScreen.css'
import type { Screen } from '../types'

export function SignupScreen({ lang, setLang, t, onSuccess, onScreen }: { lang: Lang; setLang: (lang: Lang) => void; t: (key: any) => string; onSuccess: (result: SessionResult) => void; onScreen: (screen: Screen) => void }) {
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
      setError(errorText(reason)) 
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
          <Wifi size={14} /> Host lokal aktif <span>192.168.1.24:8080</span>
        </div>
      </header>

      <div className="signup-container">
        {/* Left Column */}
        <div className="signup-left">
          
          <div className="signup-badge">
            VAULT PRIBADI • TANPA CLOUD
          </div>
          
          <h1 className="signup-hero">
            Kendalikan password<br />Anda sendiri.
          </h1>
          
          <p className="signup-description">
            Buat vault lokal terenkripsi. Tidak ada akun online, sinkronisasi cloud, atau pemulihan oleh pihak ketiga.
          </p>
          
          <div className="signup-highlight">
            <div className="signup-highlight-icon">
              <LockKeyhole size={24} />
            </div>
            <div className="signup-highlight-content">
              <h3>AES-256-GCM</h3>
              <p>Data terenkripsi saat tersimpan</p>
            </div>
          </div>
          
          <div className="signup-features">
            <div className="signup-feature-item">
              <div className="signup-feature-icon">
                <HardDrive size={18} />
              </div>
              <div className="signup-feature-text">
                <h4>Tersimpan lokal</h4>
                <p>Vault dan backup tetap di host Anda.</p>
              </div>
            </div>
            <div className="signup-feature-item">
              <div className="signup-feature-icon">
                <ShieldCheck size={18} />
              </div>
              <div className="signup-feature-text">
                <h4>Satu master password</h4>
                <p>Tidak disimpan dan tidak dikirim keluar.</p>
              </div>
            </div>
            <div className="signup-feature-item">
              <div className="signup-feature-icon">
                <KeyRound size={18} />
              </div>
              <div className="signup-feature-text">
                <h4>Recovery opsional</h4>
                <p>Simpan sendiri recovery key Anda.</p>
              </div>
            </div>
          </div>
        </div>

        {/* Right Column */}
        <div className="signup-right">
          <div className="signup-card">
            <span className="signup-card-badge">SIGN UP • FIRST SETUP</span>
            <h2 className="signup-card-title">Buat vault baru</h2>
            <p className="signup-card-subtitle">Username dan email digunakan sebagai identitas akun. Vault tetap dilindungi master password.</p>
            
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
                <label className="signup-label" htmlFor="signup-master">Master password</label>
                <div className="signup-input-wrapper">
                  <LockKeyhole size={18} className="signup-input-icon-left" />
                  <input 
                    type={showMaster ? 'text' : 'password'} 
                    required 
                    id="signup-master" className="signup-input"
                    value={master} 
                    onChange={(event) => setMaster(event.target.value)} 
                    placeholder="Buat master password"
                  />
                  <button type="button" className="signup-input-icon-right" onClick={() => setShowMaster(!showMaster)}>
                    {showMaster ? <EyeOff size={18} /> : <Eye size={18} />}
                  </button>
                </div>
              </div>
              
              <div className="signup-form-group">
                <label className="signup-label" htmlFor="signup-confirm">Konfirmasi master password</label>
                <div className="signup-input-wrapper">
                  <ShieldCheck size={18} className="signup-input-icon-left" />
                  <input 
                    type={showConfirm ? 'text' : 'password'} 
                    required 
                    id="signup-confirm" className="signup-input"
                    value={confirmation} 
                    onChange={(event) => setConfirmation(event.target.value)} 
                    placeholder="Ulangi master password"
                  />
                  <button type="button" className="signup-input-icon-right" onClick={() => setShowConfirm(!showConfirm)}>
                    {showConfirm ? <EyeOff size={18} /> : <Eye size={18} />}
                  </button>
                </div>
              </div>

              <div className="signup-strength-container">
                <div className="signup-strength-header">
                  <span className="signup-strength-label">Kekuatan master password</span>
                  <span className={`signup-strength-text signup-strength-text-${strength}`}>
                    {master ? (strength === 'good' ? 'Cukup Kuat' : strength === 'strong' ? 'Kuat' : 'Lemah') : ''}
                  </span>
                </div>
                <div className={`signup-strength-indicator signup-strength-${master ? strength : 'none'}`}>
                  <div className="signup-strength-bar"></div>
                  <div className="signup-strength-bar"></div>
                  <div className="signup-strength-bar"></div>
                  <div className="signup-strength-bar"></div>
                </div>
                <p className="signup-strength-hint">Gunakan frasa panjang yang unik dan mudah Anda ingat.</p>
              </div>

              {strength === 'weak' && master && (
                <label className="signup-checkbox-group" style={{marginTop: '-10px'}}>
                  <input 
                    type="checkbox" 
                    className="signup-checkbox"
                    checked={weakAck} 
                    onChange={(event) => setWeakAck(event.target.checked)} 
                  />
                  <span className="signup-checkbox-label" style={{fontSize: '13px', color: '#8E9B94'}}>{t('weakPasswordAck')}</span>
                </label>
              )}
              
              <div className="signup-form-group">
                <label className="signup-label">Bahasa antarmuka</label>
                <div className="signup-input-wrapper">
                  <Globe size={18} className="signup-input-icon-left" />
                  <select 
                    className="signup-select"
                    value={lang} 
                    onChange={(event) => setLang(event.target.value as Lang)}
                  >
                    <option value="id">Bahasa Indonesia</option>
                    <option value="en">English</option>
                  </select>
                  <ChevronDown size={18} className="signup-input-icon-right pointer-none" />
                </div>
              </div>

              <label className={`signup-option-card ${createRecovery ? 'active' : ''}`}>
                <input 
                  type="checkbox" 
                  className="signup-checkbox"
                  checked={createRecovery} 
                  onChange={(event) => setCreateRecovery(event.target.checked)} 
                />
                <div className="signup-option-content">
                  <strong>Buat recovery key</strong>
                  <span>Ditampilkan satu kali setelah vault berhasil dibuat.</span>
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
                  <strong>Saya memahami risiko HTTP LAN</strong>
                  <span>Traffic dan master password dapat disadap pada jaringan yang tidak tepercaya.</span>
                </div>
              </label>

              {error && <div className="signup-error">{error}</div>}
              
              <button 
                type="submit" 
                className="signup-submit" 
                disabled={isSubmitDisabled}
              >
                <ShieldCheck size={18} />
                {busy ? t('working') : 'Buat & buka vault'}
              </button>
            </form>

            <div className="signup-footer">
              <span className="signup-footer-text">Vault sudah pernah dibuat?</span>
              <button 
                type="button" 
                className="signup-login-link"
                onClick={() => onScreen('login')}
              >
                Kembali ke login &gt;
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
