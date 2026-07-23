import { render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import App from './App'

describe('application boot', () => {
  beforeEach(() => {
    sessionStorage.clear()
    localStorage.clear()
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ setup_required: true }), { status: 200, headers: { 'Content-Type': 'application/json' } })))
  })

  it('uses Indonesian by default and renders login for an empty setup', async () => {
    render(<App />)
    expect(await screen.findByText('Selamat datang kembali.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Buat akun pertama/ })).toBeInTheDocument()
  })
})
