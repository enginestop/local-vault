import { render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import App from './App'

describe('application boot', () => {
  beforeEach(() => {
    sessionStorage.clear()
    localStorage.clear()
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({
      setup_required: true,
      application_version: '1.0.0',
      api_version: 'v1',
      schema_version: 1,
      recovery_enabled: false,
      port: 8741,
      http_lan_warning: true,
    }), { status: 200, headers: { 'Content-Type': 'application/json' } })))
  })

  it('uses Indonesian by default and renders first-run setup', async () => {
    render(<App />)
    expect(await screen.findByText('Buat vault baru')).toBeInTheDocument()
    expect(screen.getByText(/HTTP LAN tidak terenkripsi/)).toBeInTheDocument()
  })
})
