import { beforeEach, describe, expect, it } from 'vitest'
import { getTabId, getToken, setToken } from './api'

describe('tab-scoped session storage', () => {
  beforeEach(() => sessionStorage.clear())

  it('never stores the bearer token in localStorage', () => {
    localStorage.clear()
    setToken('sensitive-token')
    expect(getToken()).toBe('sensitive-token')
    expect(localStorage.length).toBe(0)
    setToken(null)
    expect(getToken()).toBeNull()
  })

  it('creates a stable UUID tab owner', () => {
    const first = getTabId()
    expect(getTabId()).toBe(first)
    expect(first).toMatch(/^[0-9a-f-]{36}$/i)
  })
})
