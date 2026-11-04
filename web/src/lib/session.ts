// Platform session: the core API (futsal backend) owns users + facilities; every sport service trusts its JWT.
// Storage keys are shared with the sport UIs on purpose:
//   localStorage  "token"               core JWT (futsal api.ts and padel api.ts both send it)
//   sessionStorage "sportlens-facility"  active facility (padel files uploads under it)
//   sessionStorage "padel-media-token"   read-only token for padel <video>/<img>/CSV URLs

export type Facility = { id: string; name: string; timezone: string; created_at: string }
export type User = { id: string; email: string; full_name: string }

export const PADEL_API = (import.meta.env.VITE_PADEL_API_URL as string | undefined) ?? '/padel'
const CORE_API = (import.meta.env.VITE_FUTSAL_API_URL as string | undefined) ?? ''

function safe<T>(fn: () => T, fallback: T): T {
  try {
    return fn()
  } catch {
    return fallback
  }
}

export const getToken = () => safe(() => localStorage.getItem('token') ?? '', '')
export const setToken = (t: string) => safe(() => localStorage.setItem('token', t), undefined)

export function signOut() {
  safe(() => {
    localStorage.removeItem('token')
    sessionStorage.removeItem('padel-media-token')
    sessionStorage.removeItem('sportlens-facility')
  }, undefined)
  window.location.href = '/'
}

export function setActiveFacility(id: string) {
  safe(() => sessionStorage.setItem('sportlens-facility', id), undefined)
}

export class HttpError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

export async function http<T>(url: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers)
  const t = getToken()
  if (t) headers.set('Authorization', `Bearer ${t}`)
  if (init?.body && typeof init.body === 'string') headers.set('Content-Type', 'application/json')
  const r = await fetch(url, { ...init, headers })
  if (!r.ok) {
    const body = await r.json().catch(() => ({}))
    const detail = typeof body.detail === 'string' ? body.detail : r.statusText
    throw new HttpError(r.status, detail || `HTTP ${r.status}`)
  }
  return (r.status === 204 ? undefined : r.json()) as T
}

export const core = {
  login: async (email: string, password: string) => {
    const d = await http<{ access_token: string }>(`${CORE_API}/api/v1/auth/login`, {
      method: 'POST',
      body: JSON.stringify({ email, password }),
    })
    setToken(d.access_token)
  },
  register: (email: string, full_name: string, password: string) =>
    http<User>(`${CORE_API}/api/v1/auth/register`, {
      method: 'POST',
      body: JSON.stringify({ email, full_name, password }),
    }),
  me: () => http<User>(`${CORE_API}/api/v1/auth/me`),
  facilities: () => http<Facility[]>(`${CORE_API}/api/v1/facilities`),
  createFacility: (name: string) =>
    http<Facility>(`${CORE_API}/api/v1/facilities`, { method: 'POST', body: JSON.stringify({ name }) }),
}

// Padel media token: fetched with the JWT, refreshed well before its expiry (server TTL 6 h).
let mediaTimer: number | undefined
export async function refreshPadelMediaToken(): Promise<void> {
  const { token, expires_at } = await http<{ token: string; expires_at: number }>(`${PADEL_API}/api/media-token`)
  safe(() => sessionStorage.setItem('padel-media-token', token), undefined)
  window.clearTimeout(mediaTimer)
  const ms = Math.max(60_000, (expires_at * 1000 - Date.now()) / 2)
  mediaTimer = window.setTimeout(() => void refreshPadelMediaToken().catch(() => undefined), ms)
}
