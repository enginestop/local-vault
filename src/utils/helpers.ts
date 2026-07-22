import { ApiError, type Lang } from '../api'

export const COLORS = ['#1f2937', '#a855f7', '#f59e0b', '#e50914', '#16a34a', '#f97316', '#4d87b8', '#a66ad1']

export function colorFor(id: string): string {
  let hash = 0
  for (const character of id) hash = (hash * 31 + character.charCodeAt(0)) >>> 0
  return COLORS[hash % COLORS.length]
}

export function initials(name: string): string {
  const parts = name.trim().split(/\s+/)
  return (parts.length > 1 ? parts[0][0] + parts[1][0] : parts[0].slice(0, 2)).toUpperCase()
}

export function strengthOf(password: string): 'weak' | 'good' | 'strong' {
  let score = 0
  if (password.length >= 12) score++
  if (password.length >= 18) score++
  if (/[a-z]/.test(password) && /[A-Z]/.test(password)) score++
  if (/\d/.test(password)) score++
  if (/[^a-zA-Z0-9]/.test(password)) score++
  return score >= 4 ? 'strong' : score >= 2 ? 'good' : 'weak'
}

export function relativeTime(value: string, lang: Lang): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  const seconds = Math.round((date.getTime() - Date.now()) / 1000)
  const formatter = new Intl.RelativeTimeFormat(lang === 'id' ? 'id-ID' : 'en-US', { numeric: 'auto' })
  if (Math.abs(seconds) < 60) return formatter.format(seconds, 'second')
  const minutes = Math.round(seconds / 60)
  if (Math.abs(minutes) < 60) return formatter.format(minutes, 'minute')
  const hours = Math.round(minutes / 60)
  if (Math.abs(hours) < 24) return formatter.format(hours, 'hour')
  return formatter.format(Math.round(hours / 24), 'day')
}

export function errorText(error: unknown): string {
  if (error instanceof ApiError) return error.requestId ? `${error.detail} (${error.requestId})` : error.detail
  return error instanceof Error && error.message ? error.message : 'Request failed'
}
