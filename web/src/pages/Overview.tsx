import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { SPORTS, type MatchRow, type SportId, type Stage } from '../lib/sports'

const STAGES: { id: Stage; label: string }[] = [
  { id: 'setup', label: 'Setup' },
  { id: 'processing', label: 'Processing' },
  { id: 'review', label: 'Review' },
  { id: 'ready', label: 'Published' },
  { id: 'failed', label: 'Failed' },
]
const stageLabel = (s: Stage) => STAGES.find((x) => x.id === s)?.label ?? s

type Load = { rows: MatchRow[]; errors: Partial<Record<SportId, string>> }

function useAllMatches(facilityId: string) {
  const [state, setState] = useState<Load | null>(null)
  const load = useCallback(async () => {
    const results = await Promise.allSettled(SPORTS.map((s) => s.listMatches(facilityId)))
    const rows: MatchRow[] = []
    const errors: Load['errors'] = {}
    results.forEach((r, i) => {
      if (r.status === 'fulfilled') rows.push(...r.value)
      else errors[SPORTS[i].id] = (r.reason as Error)?.message || 'unavailable'
    })
    rows.sort((a, b) => b.createdAt.localeCompare(a.createdAt))
    setState({ rows, errors })
    return rows
  }, [facilityId])
  return { state, load }
}

const fmtDate = (iso: string) =>
  new Date(iso).toLocaleString(undefined, { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })
const fmtDur = (s?: number | null) => (s ? `${Math.floor(s / 60)}:${String(Math.round(s % 60)).padStart(2, '0')}` : '—')

export default function Overview() {
  const { facilityId = '' } = useParams()
  const { state, load } = useAllMatches(facilityId)
  const [sport, setSport] = useState<SportId | 'all'>('all')
  const [stage, setStage] = useState<Stage | 'all'>('all')

  // poll while anything is processing; stop when idle
  useEffect(() => {
    let timer: number | undefined
    let alive = true
    const tick = async () => {
      const rows = await load().catch(() => [] as MatchRow[])
      if (alive && rows.some((r) => r.stage === 'processing')) timer = window.setTimeout(tick, 15_000)
    }
    void tick()
    return () => {
      alive = false
      window.clearTimeout(timer)
    }
  }, [load])

  const rows = state?.rows ?? []
  const shown = useMemo(
    () => rows.filter((r) => (sport === 'all' || r.sport === sport) && (stage === 'all' || r.stage === stage)),
    [rows, sport, stage],
  )
  const count = (pred: (r: MatchRow) => boolean) => rows.filter(pred).length

  return (
    <div className="page-body">
      <header className="page-head">
        <div>
          <h1>Overview</h1>
          <p className="muted">Every match at this facility, across sports.</p>
        </div>
        <div className="row">
          {SPORTS.map((s) => (
            <Link key={s.id} className="btn" to={s.home(facilityId)}>
              New {s.name.toLowerCase()} match
            </Link>
          ))}
        </div>
      </header>

      <div className="status-bar" role="group" aria-label="Filter by status">
        <button type="button" className="status-btn" aria-pressed={stage === 'all'} onClick={() => setStage('all')}>
          All <strong>{state ? rows.length : '…'}</strong>
        </button>
        {STAGES.map((s) => {
          const n = state ? count((r) => r.stage === s.id) : null
          return (
            <button
              key={s.id}
              type="button"
              className={`status-btn stage-${s.id}`}
              aria-pressed={stage === s.id}
              onClick={() => setStage(stage === s.id ? 'all' : s.id)}
            >
              {s.label} <strong className={n === 0 ? 'zero' : undefined}>{n ?? '…'}</strong>
            </button>
          )
        })}
      </div>

      <ul className="sports" aria-label="Sports">
        {SPORTS.map((s) => {
          const err = state?.errors[s.id]
          const mine = rows.filter((r) => r.sport === s.id)
          const review = mine.filter((r) => r.stage === 'review').length
          const running = mine.filter((r) => r.stage === 'processing').length
          return (
            <li key={s.id} className={`sport-${s.id}`}>
              <h2>{s.name}</h2>
              <p className="meta muted small">
                {err ? (
                  <span className="down">Service unavailable: {err}</span>
                ) : (
                  <>
                    {mine.length} {mine.length === 1 ? 'match' : 'matches'}
                    {review ? ` · ${review} to review` : ''}
                    {running ? ` · ${running} processing` : ''}
                    {' · '}
                    {s.tagline}
                  </>
                )}
              </p>
              <div className="actions">
                <Link className="btn primary" to={s.home(facilityId)}>
                  Open {s.name}
                </Link>
              </div>
            </li>
          )
        })}
      </ul>

      <section className="panel">
        <div className="row between wrap-gap">
          <h2>Matches</h2>
          <div className="segmented" role="group" aria-label="Sport filter">
            {(['all', ...SPORTS.map((s) => s.id)] as const).map((id) => (
              <button key={id} type="button" className={sport === id ? 'on' : ''} aria-pressed={sport === id} onClick={() => setSport(id)}>
                {id === 'all' ? 'All' : SPORTS.find((s) => s.id === id)?.name}
              </button>
            ))}
          </div>
        </div>
        {!state ? (
          <p className="muted">Loading matches…</p>
        ) : shown.length === 0 ? (
          <div className="empty">
            <p>
              {rows.length === 0
                ? 'No matches yet. Upload a recording to get player and match stats.'
                : `No ${sport === 'all' ? '' : `${sport} `}matches${stage !== 'all' ? ` in ${stageLabel(stage).toLowerCase()}` : ''}.`}
            </p>
            {rows.length === 0 && (
              <div className="row">
                {SPORTS.map((s) => (
                  <Link key={s.id} className="btn" to={s.home(facilityId)}>
                    Upload a {s.name.toLowerCase()} match
                  </Link>
                ))}
              </div>
            )}
          </div>
        ) : (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Match</th>
                  <th>Sport</th>
                  <th>Status</th>
                  <th className="num">Length</th>
                  <th>Added</th>
                </tr>
              </thead>
              <tbody>
                {shown.map((r) => (
                  <tr key={`${r.sport}-${r.id}`}>
                    <td className="title">
                      <Link to={r.href}>{r.title}</Link>
                    </td>
                    <td>
                      <span className={`chip sport-${r.sport}`}>{r.sport}</span>
                    </td>
                    <td>
                      <span className={`chip stage-${r.stage}`} title={r.rawStatus}>
                        {stageLabel(r.stage)}
                        {r.stage === 'processing' && r.progress ? ` ${Math.round(r.progress * 100)}%` : ''}
                      </span>
                    </td>
                    <td className="num">{fmtDur(r.durationS)}</td>
                    <td className="muted">{fmtDate(r.createdAt)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  )
}
