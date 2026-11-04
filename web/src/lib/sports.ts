// Sport registry: the one place that knows how each sport service names things.
// Adding a sport = a service behind the gateway + an entry here + a module under src/sports/.

import { http, PADEL_API } from './session'

export type SportId = 'futsal' | 'padel'
export type Stage = 'setup' | 'processing' | 'review' | 'ready' | 'failed'

export type MatchRow = {
  sport: SportId
  id: string
  title: string
  stage: Stage
  rawStatus: string
  progress?: number
  createdAt: string
  durationS?: number | null
  href: string
}

export type Column = { key: string; label: string; unit?: string; digits?: number }

// One row of a cross-match player table; numbers are summed (or maxed / averaged, see SportDef.aggregate)
export type PlayerLine = { key: string; name: string; team?: string; values: Record<string, number | null> }

export type SportDef = {
  id: SportId
  name: string
  tagline: string
  home: (facilityId: string) => string
  listMatches: (facilityId: string) => Promise<MatchRow[]>
  /** per-match player lines, only for matches with results */
  playerLines: (facilityId: string, m: MatchRow) => Promise<PlayerLine[]>
  columns: Column[]
  /** how a column combines across matches; default sum */
  aggregate: Record<string, 'sum' | 'max' | 'mean'>
}

const FUTSAL_STAGE: Record<string, Stage> = {
  draft: 'setup',
  uploaded: 'setup',
  processing: 'processing',
  needs_review: 'review',
  published: 'ready',
  archived: 'ready',
  failed: 'failed',
}
const PADEL_STAGE: Record<string, Stage> = {
  uploaded: 'setup',
  calibrated: 'setup',
  queued: 'processing',
  processing: 'processing',
  done: 'review', // padel reports are reviewable as soon as they exist
  failed: 'failed',
}

type FutsalMatch = { id: string; title: string; status: string; created_at: string }
type FutsalStats = {
  by_player: {
    player_id: string
    display_name: string
    team_id?: string | null
    goal: number
    assist?: number
    shot: number
    shot_on_target?: number
    pass: number
    pass_received?: number
    dribble?: number
    interception?: number
    minutes?: number
    distance_m?: number | null
    top_speed_kmh?: number | null
    pass_accuracy_pct?: number | null
  }[]
}
type PadelMatch = {
  id: string
  title: string
  status: string
  progress: number
  created_at: string
  duration_s: number | null
}
type PadelSummary = {
  players: {
    id: number
    name: string
    team: number
    stats: {
      shots: number
      winners?: number
      errors?: number
      distance_m: number
      max_speed_kmh: number | null
      sprints: number
      volleys: number
      overheads: number
      zone_pct: { net: number | null }
      ball_speed_kmh?: { avg: number | null }
    }
  }[]
  teams: { id: number; name: string }[]
}

const futsal: SportDef = {
  id: 'futsal',
  name: 'Futsal',
  tagline: 'Multi-camera 5v5: tracking, possession, passes, shots and goals',
  home: (f) => `/facilities/${f}/futsal`,
  async listMatches(f) {
    const ms = await http<FutsalMatch[]>(`/api/v1/facilities/${f}/matches`)
    return ms.map((m) => ({
      sport: 'futsal',
      id: m.id,
      title: m.title,
      stage: FUTSAL_STAGE[m.status] ?? 'setup',
      rawStatus: m.status,
      createdAt: m.created_at,
      href: `/facilities/${f}/matches/${m.id}`,
    }))
  },
  async playerLines(f, m) {
    const s = await http<FutsalStats>(`/api/v1/facilities/${f}/matches/${m.id}/stats`)
    return s.by_player.map((p) => ({
      key: p.player_id,
      name: p.display_name,
      values: {
        minutes: p.minutes ?? null,
        goal: p.goal,
        assist: p.assist ?? 0,
        shot: p.shot,
        shot_on_target: p.shot_on_target ?? 0,
        pass: p.pass,
        pass_accuracy_pct: p.pass_accuracy_pct ?? null,
        dribble: p.dribble ?? 0,
        interception: p.interception ?? 0,
        distance_m: p.distance_m ?? null,
        top_speed_kmh: p.top_speed_kmh ?? null,
      },
    }))
  },
  columns: [
    { key: 'minutes', label: 'Min', digits: 0 },
    { key: 'goal', label: 'Goals' },
    { key: 'assist', label: 'Ast' },
    { key: 'shot', label: 'Shots' },
    { key: 'shot_on_target', label: 'On tgt' },
    { key: 'pass', label: 'Passes' },
    { key: 'pass_accuracy_pct', label: 'Pass %', unit: '%' },
    { key: 'dribble', label: 'Dribbles' },
    { key: 'interception', label: 'Int' },
    { key: 'distance_m', label: 'Dist', unit: ' m' },
    { key: 'top_speed_kmh', label: 'Top', unit: ' km/h', digits: 1 },
  ],
  aggregate: { pass_accuracy_pct: 'mean', top_speed_kmh: 'max' },
}

const padel: SportDef = {
  id: 'padel',
  name: 'Padel',
  tagline: 'One fixed camera: player tracking, shots, strokes, rallies and points',
  home: (f) => `/facilities/${f}/padel`,
  async listMatches(f) {
    const ms = await http<PadelMatch[]>(`${PADEL_API}/api/matches?facility_id=${encodeURIComponent(f)}`)
    return ms.map((m) => ({
      sport: 'padel',
      id: m.id,
      title: m.title,
      stage: PADEL_STAGE[m.status] ?? 'setup',
      rawStatus: m.status,
      progress: m.progress,
      createdAt: m.created_at,
      durationS: m.duration_s,
      href: `/facilities/${f}/padel#/${m.status === 'done' ? `m/${m.id}` : m.status === 'uploaded' ? `m/${m.id}/calibrate` : ''}`,
    }))
  },
  async playerLines(_f, m) {
    const s = await http<PadelSummary>(`${PADEL_API}/api/matches/${m.id}/summary`)
    return s.players.map((p) => {
      // padel players are named per match in review; a reviewed name is the cross-match key, while the
      // default "Player N" is a different person in every match and must not be merged
      const unnamed = /^player \d+$/i.test(p.name.trim())
      return {
      key: unnamed ? `${m.id}:${p.id}` : p.name.trim().toLowerCase(),
      name: unnamed ? `${p.name} · ${m.title}` : p.name,
      team: s.teams[p.team]?.name,
      values: {
        shots: p.stats.shots,
        winners: p.stats.winners ?? null,
        errors: p.stats.errors ?? null,
        volleys: p.stats.volleys,
        overheads: p.stats.overheads,
        net_pct: p.stats.zone_pct?.net ?? null,
        distance_m: p.stats.distance_m,
        sprints: p.stats.sprints,
        max_speed_kmh: p.stats.max_speed_kmh,
        ball_speed_kmh: p.stats.ball_speed_kmh?.avg ?? null,
      },
      }
    })
  },
  columns: [
    { key: 'shots', label: 'Shots' },
    { key: 'winners', label: 'Winners' },
    { key: 'errors', label: 'Errors' },
    { key: 'volleys', label: 'Volleys' },
    { key: 'overheads', label: 'Overheads' },
    { key: 'net_pct', label: 'At net', unit: '%' },
    { key: 'distance_m', label: 'Dist', unit: ' m' },
    { key: 'sprints', label: 'Sprints' },
    { key: 'max_speed_kmh', label: 'Top', unit: ' km/h', digits: 1 },
    { key: 'ball_speed_kmh', label: 'Ball', unit: ' km/h', digits: 0 },
  ],
  aggregate: { net_pct: 'mean', max_speed_kmh: 'max', ball_speed_kmh: 'mean' },
}

export const SPORTS: SportDef[] = [futsal, padel]
export const sportById = (id: string) => SPORTS.find((s) => s.id === id)

/** Run fn over items with at most `limit` in flight (keeps dashboards from flooding the APIs). */
export async function pool<T, R>(items: T[], limit: number, fn: (t: T) => Promise<R>): Promise<(R | null)[]> {
  const out: (R | null)[] = new Array(items.length).fill(null)
  let next = 0
  async function lane() {
    while (next < items.length) {
      const i = next++
      try {
        out[i] = await fn(items[i])
      } catch {
        out[i] = null
      }
    }
  }
  await Promise.all(Array.from({ length: Math.min(limit, items.length) }, lane))
  return out
}

export type PlayerTotal = { key: string; name: string; team?: string; matches: number; values: Record<string, number | null> }

/** Combine per-match lines into per-player totals following the sport's aggregate rules. */
export function combine(sport: SportDef, perMatch: PlayerLine[][]): PlayerTotal[] {
  const acc = new Map<string, PlayerTotal & { n: Record<string, number> }>()
  for (const lines of perMatch) {
    for (const l of lines) {
      const row = acc.get(l.key) ?? { key: l.key, name: l.name, team: l.team, matches: 0, values: {}, n: {} }
      row.matches += 1
      row.name = l.name
      for (const [k, v] of Object.entries(l.values)) {
        if (v == null) {
          if (!(k in row.values)) row.values[k] = null
          continue
        }
        const prev = row.values[k] ?? null
        const rule = sport.aggregate[k] ?? 'sum'
        if (rule === 'max') row.values[k] = prev == null ? v : Math.max(prev, v)
        else if (rule === 'mean') {
          row.n[k] = (row.n[k] ?? 0) + 1
          row.values[k] = prev == null ? v : prev + (v - prev) / row.n[k]
        } else row.values[k] = (prev ?? 0) + v
      }
      acc.set(l.key, row)
    }
  }
  return [...acc.values()].map(({ n: _n, ...r }) => r)
}
