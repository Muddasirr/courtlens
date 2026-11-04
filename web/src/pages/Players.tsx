import { useEffect, useMemo, useState } from 'react'
import { useParams } from 'react-router-dom'
import { combine, pool, SPORTS, type PlayerTotal, type SportId } from '../lib/sports'

// Cross-match player table per sport. Counts are model estimates unless the match was reviewed;
// futsal players are roster entities (stable ids), padel players are matched by their reviewed name.
const MAX_MATCHES = 30

export default function Players() {
  const { facilityId = '' } = useParams()
  const [sportId, setSportId] = useState<SportId>('futsal')
  const [rows, setRows] = useState<PlayerTotal[] | null>(null)
  const [meta, setMeta] = useState({ used: 0, total: 0, failed: 0 })
  const [error, setError] = useState('')
  const [sort, setSort] = useState<{ key: string; desc: boolean }>({ key: 'matches', desc: true })
  const sport = SPORTS.find((s) => s.id === sportId)!

  useEffect(() => {
    let alive = true
    setRows(null)
    setError('')
    ;(async () => {
      const all = await sport.listMatches(facilityId)
      const withResults = all.filter((m) => m.stage === 'review' || m.stage === 'ready')
      const used = withResults.slice(0, MAX_MATCHES)
      const lines = await pool(used, 4, (m) => sport.playerLines(facilityId, m))
      if (!alive) return
      const ok = lines.filter((l): l is NonNullable<typeof l> => l !== null)
      setMeta({ used: ok.length, total: withResults.length, failed: lines.length - ok.length })
      setRows(combine(sport, ok))
    })().catch((e: Error) => alive && setError(e.message))
    return () => {
      alive = false
    }
  }, [facilityId, sport])

  const sorted = useMemo(() => {
    if (!rows) return []
    const val = (r: PlayerTotal) => (sort.key === 'matches' ? r.matches : sort.key === 'name' ? r.name : r.values[sort.key])
    return [...rows].sort((a, b) => {
      const x = val(a)
      const y = val(b)
      if (x == null) return 1
      if (y == null) return -1
      const c = typeof x === 'string' ? x.localeCompare(String(y)) : x - (y as number)
      return sort.desc ? -c : c
    })
  }, [rows, sort])

  const head = (key: string, label: string, num = true) => (
    <th className={num ? 'num' : ''} aria-sort={sort.key === key ? (sort.desc ? 'descending' : 'ascending') : 'none'}>
      <button type="button" className="th-btn" onClick={() => setSort({ key, desc: sort.key === key ? !sort.desc : true })}>
        {label}
        {sort.key === key ? (sort.desc ? ' ↓' : ' ↑') : ''}
      </button>
    </th>
  )

  return (
    <div className="page-body">
      <div className="row between wrap-gap">
        <div>
          <h1>Players</h1>
          <p className="muted">Season totals across analysed matches. Click a column to sort.</p>
        </div>
        <div className="segmented" role="group" aria-label="Sport">
          {SPORTS.map((s) => (
            <button key={s.id} type="button" className={sportId === s.id ? 'on' : ''} onClick={() => setSportId(s.id)}>
              {s.name}
            </button>
          ))}
        </div>
      </div>
      <section className="panel">
        {error ? (
          <p className="notice error">{error}</p>
        ) : !rows ? (
          <p className="muted">Collecting match stats…</p>
        ) : rows.length === 0 ? (
          <p className="muted">No analysed {sport.name.toLowerCase()} matches yet.</p>
        ) : (
          <>
            <p className="muted small">
              {meta.used} of {meta.total} analysed matches
              {meta.total > MAX_MATCHES ? ` (latest ${MAX_MATCHES})` : ''}
              {meta.failed ? ` · ${meta.failed} could not be read` : ''} · values are <em>estimated</em> unless confirmed in
              review{sport.id === 'padel' ? ' · players are grouped by the name given in review' : ''}.
            </p>
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    {head('name', 'Player', false)}
                    {head('matches', 'MP')}
                    {sport.columns.map((c) => head(c.key, c.label))}
                  </tr>
                </thead>
                <tbody>
                  {sorted.map((r) => (
                    <tr key={r.key}>
                      <td>
                        <strong>{r.name}</strong>
                        {r.team && <span className="muted small"> · {r.team}</span>}
                      </td>
                      <td className="num">{r.matches}</td>
                      {sport.columns.map((c) => {
                        const v = r.values[c.key]
                        return (
                          <td key={c.key} className="num">
                            {v == null ? <span className="muted">—</span> : `${v.toFixed(c.digits ?? (Number.isInteger(v) ? 0 : 1))}${c.unit ?? ''}`}
                          </td>
                        )
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </section>
    </div>
  )
}
