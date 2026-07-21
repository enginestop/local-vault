import { render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import App from './App'

describe('application boot', () => {
  beforeEach(() => {
    sessionStorage.clear()
    localStorage.clear()
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ setup_required: true }), { status: 200, headers: { 'Content-Type': 'application/json' } })))
  })

  it('uses Indonesian by default and renders the login screen', async () => {
    render(<App />)
    expect(await screen.findByText('Masuk ke LocalVault')).toBeInTheDocument()
    expect(screen.getByText('Belum punya akun?')).toBeInTheDocument()
  })
})
