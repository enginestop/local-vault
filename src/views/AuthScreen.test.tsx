import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { api } from '../api'
import { AuthScreen } from './AuthScreen'
import { SignupScreen } from './SignupScreen'

const t = (key: string) => ({
  usernameOrEmail: 'Username atau email',
  masterPassword: 'Master password',
  openVault: 'Buka vault',
  createFirstAccount: 'Buat akun pertama',
  useRecovery: 'Gunakan recovery key',
  usernameLabel: 'Username',
  usernamePlaceholder: 'Buat username',
  emailLabel: 'Email',
  emailPlaceholder: 'nama@contoh.com',
  weakPasswordAck: 'Password lemah',
  working: 'Memproses',
}[key] ?? key)

const session = { token: 'token', session_id: 'session', user_id: 'user', username: 'owner', email: 'owner@example.com' }

describe('authentication flow', () => {
  it('opens signup from login only when setup is required', () => {
    const onScreen = vi.fn()
    render(<AuthScreen screen="login" setupRequired lang="id" setLang={vi.fn()} t={t} onSuccess={vi.fn()} onScreen={onScreen} retry={vi.fn()} />)
    fireEvent.click(screen.getByRole('button', { name: /Buat akun pertama/ }))
    expect(onScreen).toHaveBeenCalledWith('signup')
  })

  it('submits login with username/email to the sessions login endpoint', async () => {
    const login = vi.spyOn(api, 'login').mockResolvedValue(session)
    render(<AuthScreen screen="login" setupRequired={false} lang="id" setLang={vi.fn()} t={t} onSuccess={vi.fn()} onScreen={vi.fn()} retry={vi.fn()} />)
    fireEvent.change(screen.getByLabelText('Username atau email'), { target: { value: 'owner@example.com' } })
    fireEvent.change(screen.getByLabelText('Master password'), { target: { value: 'correct horse battery staple' } })
    fireEvent.click(screen.getByRole('button', { name: 'Buka vault' }))
    await waitFor(() => expect(login).toHaveBeenCalledWith('owner@example.com', 'correct horse battery staple'))
    login.mockRestore()
  })

  it('shows username and email and submits them through register', async () => {
    const register = vi.spyOn(api, 'register').mockResolvedValue({ ...session, recovery_key: null })
    render(<SignupScreen lang="id" setLang={vi.fn()} t={t} onSuccess={vi.fn()} onScreen={vi.fn()} />)
    expect(screen.getByLabelText('Username')).toBeInTheDocument()
    expect(screen.getByLabelText('Email')).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('Username'), { target: { value: 'owner' } })
    fireEvent.change(screen.getByLabelText('Email'), { target: { value: 'owner@example.com' } })
    fireEvent.change(screen.getByPlaceholderText('Buat master password'), { target: { value: 'LongEnoughPassword1!' } })
    fireEvent.change(screen.getByPlaceholderText('Ulangi master password'), { target: { value: 'LongEnoughPassword1!' } })
    fireEvent.click(screen.getAllByRole('checkbox').at(-1)!)
    fireEvent.click(screen.getByRole('button', { name: 'Buat & buka vault' }))
    await waitFor(() => expect(register).toHaveBeenCalledWith(expect.objectContaining({
      username: 'owner',
      email: 'owner@example.com',
      master_password: 'LongEnoughPassword1!',
      confirm_master_password: 'LongEnoughPassword1!',
    })))
    register.mockRestore()
  })
})
