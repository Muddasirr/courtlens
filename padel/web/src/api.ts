import type { CourtModel, Match, Pt, Report } from './types'

export interface Share { token: string; match_id: string; created_at: string; revoked: boolean }
export interface SharedMatch { id: string; title: string; created_at: string | null; fps: number; n_frames: number; width: number; height: number }

/** Where a share token opens the read-only report. SportLens overrides this with its own route. */
export const links = { share: (token: string) => `${window.location.origin}${window.location.pathname}#/s/${token}` }

// VITE_PADEL_API_URL: set by the unified SportLens web app (gateway prefix /api/padel); standalone uses VITE_API_URL
const BASE = ((import.meta.env.VITE_PADEL_API_URL ?? import.meta.env.VITE_API_URL) as string | undefined) ?? ''

// Optional server token (PADEL_API_TOKEN): asked once on a 401, kept in this browser.
// Inside SportLens the platform sign-in JWT ("token") is sent instead, and media URLs carry a short-lived
// read-only media token ("padel-media-token", refreshed by the shell) so the JWT never lands in a URL.
const TOKEN_KEY = 'padel-token'
function read(key: string, store: () => Storage = () => localStorage): string {
  try {
    return store().getItem(key) ?? ''
  } catch {
    return ''
  }
}
function token(): string {
  return read(TOKEN_KEY) || read('token')
}
function withToken(url: string): string {
  const t = read(TOKEN_KEY) || read('padel-media-token', () => sessionStorage)
  return t ? `${url}${url.includes('?') ? '&' : '?'}token=${encodeURIComponent(t)}` : url
}

async function req<T>(path: string, init?: RequestInit, retried = false): Promise<T> {
  const headers = new Headers(init?.headers)
  if (token()) headers.set('Authorization', `Bearer ${token()}`)
  const r = await fetch(BASE + path, { ...init, headers })
  if (r.status === 401 && !retried && !read('token')) {
    const t = window.prompt('Access token for this PadelLens server')
    if (t) {
      try {
        localStorage.setItem(TOKEN_KEY, t)
      } catch {
        /* storage blocked: token lasts for this request only */
      }
      return req<T>(path, init, true)
    }
  }
  if (!r.ok) {
    let msg = `${r.status} ${r.statusText}`
    try {
      const j = await r.json()
      if (j.detail) msg = typeof j.detail === 'string' ? j.detail : JSON.stringify(j.detail)
    } catch {
      /* not json */
    }
    throw new Error(msg)
  }
  return r.json() as Promise<T>
}

const json = (method: string, body: unknown): RequestInit => ({
  method,
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body),
})

export const api = {
  court: () => req<CourtModel>('/api/court'),
  matches: () => {
    const facility = read('sportlens-facility', () => sessionStorage)
    return req<Match[]>(facility ? `/api/matches?facility_id=${encodeURIComponent(facility)}` : '/api/matches')
  },
  match: (id: string) => req<Match>(`/api/matches/${id}`),
  remove: (id: string) => req(`/api/matches/${id}`, { method: 'DELETE' }),
  analyze: (id: string) => req<Match>(`/api/matches/${id}/analyze`, { method: 'POST' }),
  report: (id: string) => req<Report>(`/api/matches/${id}/report`),
  calibrate: (id: string, points: Record<string, Pt>, t: number, snap: boolean, saveCamera?: string) =>
    req<{ match: Match; refine: Record<string, number>; projected_landmarks: Record<string, Pt> }>(
      `/api/matches/${id}/calibration`,
      json('PUT', { points, t, snap, save_camera: saveCamera || null }),
    ),
  cameras: () => {
    const facility = read('sportlens-facility', () => sessionStorage)
    return req<{ id: string; name: string }[]>(facility ? `/api/cameras?facility_id=${encodeURIComponent(facility)}` : '/api/cameras')
  },
  useCamera: (id: string, cameraId: string) =>
    req<Match>(`/api/matches/${id}/camera/${cameraId}`, { method: 'POST' }),
  review: (id: string, body: Record<string, Record<string, unknown>>) =>
    req<Match>(`/api/matches/${id}/review`, json('PATCH', body)),
  frameUrl: (id: string, t: number, overlay = false, bust = '') =>
    withToken(`${BASE}/api/matches/${id}/frame?t=${t.toFixed(2)}${overlay ? '&overlay=true' : ''}${bust ? `&v=${bust}` : ''}`),
  videoUrl: (id: string) => withToken(`${BASE}/api/matches/${id}/video`),
  exportUrl: (id: string, table: string) => withToken(`${BASE}/api/matches/${id}/export/${table}.csv`),
  reportUrl: (id: string) => withToken(`${BASE}/api/matches/${id}/report`),
  share: (id: string) => req<{ share: Share | null }>(`/api/matches/${id}/share`),
  createShare: (id: string) => req<{ share: Share }>(`/api/matches/${id}/share`, { method: 'POST' }),
  revokeShare: (id: string) => req<{ revoked: number }>(`/api/matches/${id}/share`, { method: 'DELETE' }),
  // public share links: no sign-in, the token in the path is the only credential
  shared: async (token: string): Promise<{ match: SharedMatch; report: Report }> => {
    const r = await fetch(`${BASE}/api/public/share/${encodeURIComponent(token)}`)
    if (!r.ok) throw new Error(r.status === 404 ? 'This link has been turned off or does not exist.' : `${r.status} ${r.statusText}`)
    return r.json()
  },
  sharedVideoUrl: (token: string) => `${BASE}/api/public/share/${encodeURIComponent(token)}/video`,

  upload(file: File, title: string, onProgress: (p: number) => void): Promise<Match> {
    return new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest()
      const fd = new FormData()
      fd.append('file', file)
      fd.append('title', title)
      const facility = read('sportlens-facility', () => sessionStorage)
      if (facility) fd.append('facility_id', facility)
      xhr.open('POST', `${BASE}/api/matches`)
      if (token()) xhr.setRequestHeader('Authorization', `Bearer ${token()}`)
      xhr.upload.onprogress = (e) => e.lengthComputable && onProgress(e.loaded / e.total)
      xhr.onload = () =>
        xhr.status < 300 ? resolve(JSON.parse(xhr.responseText)) : reject(new Error(xhr.responseText || xhr.statusText))
      xhr.onerror = () => reject(new Error('upload failed'))
      xhr.send(fd)
    })
  },
}

/** image px -> court metres is H; this applies H^-1 (metres -> px) for overlays. */
export function invert3(m: number[][]): number[][] {
  const [a, b, c] = m[0]
  const [d, e, f] = m[1]
  const [g, h, i] = m[2]
  const A = e * i - f * h
  const B = -(d * i - f * g)
  const C = d * h - e * g
  const det = a * A + b * B + c * C
  return [
    [A / det, -(b * i - c * h) / det, (b * f - c * e) / det],
    [B / det, (a * i - c * g) / det, -(a * f - c * d) / det],
    [C / det, -(a * h - b * g) / det, (a * e - b * d) / det],
  ]
}

export function project(m: number[][], p: Pt): Pt {
  const x = m[0][0] * p[0] + m[0][1] * p[1] + m[0][2]
  const y = m[1][0] * p[0] + m[1][1] * p[1] + m[1][2]
  const w = m[2][0] * p[0] + m[2][1] * p[1] + m[2][2]
  return [x / w, y / w]
}

/** court metres -> image px, including the calibration's radial lens distortion (division model). */
export function toImage(cal: { H: number[][]; image_size: [number, number]; k1?: number }, Hinv: number[][], m: Pt): Pt {
  const [ux, uy] = project(Hinv, m)
  const k1 = cal.k1 ?? 0
  if (!k1) return [ux, uy]
  const [w, h] = cal.image_size
  const cx = w / 2
  const cy = h / 2
  const s = Math.hypot(w, h) / 2
  const qx = (ux - cx) / s
  const qy = (uy - cy) / s
  const ru = Math.hypot(qx, qy)
  if (ru < 1e-9) return [ux, uy]
  const rd = (1 - Math.sqrt(Math.max(0, 1 - 4 * k1 * ru * ru))) / (2 * k1 * ru)
  return [cx + (qx * rd) / ru * s, cy + (qy * rd) / ru * s]
}

export const fmtTime = (s: number) => {
  const m = Math.floor(s / 60)
  return `${m}:${Math.floor(s % 60).toString().padStart(2, '0')}`
}

export const playerTag = (id: number) => `${'AB'[id < 2 ? 0 : 1]}${(id % 2) + 1}`
