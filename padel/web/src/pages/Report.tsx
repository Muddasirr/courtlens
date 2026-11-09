import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api, fmtTime, invert3, links, playerTag, toImage, type Share } from '../api'
import { Bars, Heatmap, ZoneSplit } from '../components/Charts'
import Court, { teamColor } from '../components/Court'
import type { Player, PlayerStats, Report, Shot } from '../types'

type Tab = 'players' | 'pairs' | 'rallies' | 'shots' | 'quality'
const TABS: [Tab, string][] = [
  ['players', 'Players'],
  ['pairs', 'Pairs'],
  ['rallies', 'Rallies'],
  ['shots', 'Shots'],
  ['quality', 'About this analysis'],
]
type Review = (b: Record<string, Record<string, unknown>>) => void
interface Head { title: string; createdAt: string | null }

/** Match report. `id` = signed-in, editable; `shareToken` = public read-only link (no sign-in). */
export default function ReportPage({ id, shareToken }: { id?: string; shareToken?: string }) {
  const readOnly = !!shareToken
  const [head, setHead] = useState<Head | null>(null)
  const [rep, setRep] = useState<Report | null>(null)
  const [err, setErr] = useState('')
  const [tab, setTab] = useState<Tab>('players')
  const [now, setNow] = useState(0)
  const video = useRef<HTMLVideoElement>(null)

  const load = useCallback(() => {
    if (shareToken) {
      api.shared(shareToken)
        .then(({ match, report }) => {
          setHead({ title: match.title, createdAt: match.created_at })
          setRep(report)
        })
        .catch((e) => setErr(e.message))
    } else if (id) {
      api.match(id).then((m) => setHead({ title: m.title, createdAt: m.created_at })).catch((e) => setErr(e.message))
      api.report(id).then(setRep).catch((e) => setErr(e.message))
    }
  }, [id, shareToken])
  useEffect(load, [load])

  const seek = (t: number) => {
    if (video.current) {
      video.current.currentTime = Math.max(0, t)
      video.current.play().catch(() => undefined)
    }
  }
  const review: Review = async (body) => {
    if (!id) return
    try {
      await api.review(id, body)
      setRep(await api.report(id))
    } catch (e) {
      setErr((e as Error).message)
    }
  }

  if (err && !rep) return <div className="notice error" role="alert">{err}</div>
  if (!rep || !head) return <p className="muted">Loading the match report…</p>
  const names = rep.players.map((p) => p.name)
  const idx = Math.min(rep.replay.players.length - 1, Math.max(0, Math.round(now * rep.replay.hz)))
  const m = rep.match
  const videoSrc = shareToken ? api.sharedVideoUrl(shareToken) : api.videoUrl(id!)

  return (
    <div className="report">
      <header className="report-head">
        <div className="report-title">
          {!readOnly && <a className="back" href="#/">All matches</a>}
          <h1>{head.title}</h1>
          <p className="secondary">
            {head.createdAt && <>{fmtDate(head.createdAt)} · </>}
            {fmtTime(m.duration_s)} of video · {m.rallies} rallies · {m.hits} shots
          </p>
        </div>
        {!readOnly && id && (
          <div className="report-actions">
            <SharePanel id={id} />
            <details className="menu">
              <summary className="btn">Download</summary>
              <div className="menu-body" role="menu">
                {['shots', 'players', 'pairs', 'rallies'].map((t) => (
                  <a key={t} role="menuitem" href={api.exportUrl(id, t)} download>{t[0].toUpperCase() + t.slice(1)} (CSV)</a>
                ))}
                <a role="menuitem" href={api.reportUrl(id)} download={`padel_${id}_report.json`}>Full report (JSON)</a>
              </div>
            </details>
          </div>
        )}
      </header>

      <dl className="summary">
        {m.score && m.points_decided ? (
          <Stat label={m.outcome_label === 'confirmed' ? 'Score' : 'Score (estimated)'}
            value={m.score.sets.map((g: number[]) => g.join('–')).join('  ')}
            sub={`${m.points_decided} points decided`} />
        ) : null}
        <Stat label="Rallies" value={m.rallies} />
        <Stat label="Shots" value={m.hits} />
        <Stat label="Average rally" value={m.avg_rally_shots ?? '–'} sub={m.avg_rally_s ? `shots, ${m.avg_rally_s} s` : 'shots'} />
        <Stat label="Longest rally" value={m.max_rally_shots ?? '–'} sub="shots" />
        {m.time_in_play_pct != null && (
          <Stat label="Ball in play" value={`${m.time_in_play_pct}%`} sub={m.time_in_play_s != null ? `${fmtTime(m.time_in_play_s)} in total` : undefined} />
        )}
      </dl>

      <div className="player-layout">
        <div className="media">
          <VideoOverlay ref={video} src={videoSrc} rep={rep} idx={idx} onTime={setNow} />
          <Timeline rep={rep} now={now} seek={seek} />
        </div>
        <figure className="court-panel">
          <Court players={rep.replay.players[idx]} names={names} height={420} />
          <figcaption className="row small secondary">
            {rep.teams.map((t) => (
              <span key={t.id} className="team-chip"><i style={{ background: teamColor(t.id) }} />{t.name}</span>
            ))}
            <span>· live positions</span>
          </figcaption>
        </figure>
      </div>

      <div className="tabs" role="tablist" aria-label="Report sections">
        {TABS.map(([t, label]) => (
          <button key={t} role="tab" aria-selected={tab === t} className={tab === t ? 'on' : ''} onClick={() => setTab(t)}>{label}</button>
        ))}
      </div>
      {err && <p className="notice error" role="alert">{err}</p>}

      <section role="tabpanel" aria-label={TABS.find(([t]) => t === tab)?.[1]}>
        {tab === 'players' && <Players rep={rep} readOnly={readOnly} review={review} />}
        {tab === 'pairs' && <Pairs rep={rep} names={names} readOnly={readOnly} review={review} seek={seek} />}
        {tab === 'rallies' && <Rallies rep={rep} names={names} seek={seek} review={review} readOnly={readOnly} />}
        {tab === 'shots' && <Shots rep={rep} names={names} seek={seek} review={review} now={now} readOnly={readOnly} />}
        {tab === 'quality' && <Quality rep={rep} />}
      </section>

      <p className="footnote secondary small">
        Positions, distances and speeds are measured on the calibrated court. Shots, stroke types and point winners are
        model estimates{readOnly ? '' : ' until confirmed in the Shots and Rallies tabs'}.
      </p>
    </div>
  )
}

const fmtDate = (iso: string) =>
  new Date(iso).toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' })

function Stat({ label, value, sub }: { label: string; value: string | number; sub?: string }) {
  return (
    <div className="stat">
      <dt>{label}</dt>
      <dd>
        <span className="value num">{value}</span>
        {sub && <span className="sub">{sub}</span>}
      </dd>
    </div>
  )
}

function SharePanel({ id }: { id: string }) {
  const [share, setShare] = useState<Share | null | undefined>(undefined)
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState('')
  useEffect(() => {
    if (open && share === undefined) api.share(id).then((r) => setShare(r.share)).catch((e) => setMsg(e.message))
  }, [open, share, id])
  const url = share ? links.share(share.token) : ''
  const act = async (fn: () => Promise<void>) => {
    setBusy(true)
    setMsg('')
    try {
      await fn()
    } catch (e) {
      setMsg((e as Error).message)
    } finally {
      setBusy(false)
    }
  }
  return (
    <details className="menu share" open={open} onToggle={(e) => setOpen((e.target as HTMLDetailsElement).open)}>
      <summary className="btn primary">Share</summary>
      <div className="menu-body share-body">
        {share === undefined ? (
          <p className="secondary small">Checking for a link…</p>
        ) : share ? (
          <>
            <p className="small">Anyone with this link can watch the video and see this report. They cannot edit it.</p>
            <div className="row">
              <input readOnly value={url} aria-label="Share link" onFocus={(e) => e.target.select()} />
              <button type="button" className="primary" onClick={() => navigator.clipboard?.writeText(url).then(() => setMsg('Link copied.'), () => setMsg('Copy failed: select the link and copy it.'))}>
                Copy
              </button>
            </div>
            <div className="row small">
              <a href={url} target="_blank" rel="noreferrer">Open as a visitor</a>
              <button type="button" className="ghost danger small" disabled={busy}
                onClick={() => act(async () => { await api.revokeShare(id); setShare(null) })}>
                Turn off link
              </button>
            </div>
          </>
        ) : (
          <>
            <p className="small">Create a link anyone can open without signing in: video, stats and rallies, read-only.</p>
            <button type="button" className="primary" disabled={busy}
              onClick={() => act(async () => setShare((await api.createShare(id)).share))}>
              {busy ? 'Creating…' : 'Create link'}
            </button>
          </>
        )}
        {msg && <p className="small secondary" role="status">{msg}</p>}
      </div>
    </details>
  )
}

const VideoOverlay = ({ ref, src, rep, idx, onTime }: {
  ref: React.RefObject<HTMLVideoElement | null>; src: string; rep: Report; idx: number; onTime: (t: number) => void
}) => {
  const canvas = useRef<HTMLCanvasElement>(null)
  const Hinv = useMemo(() => invert3(rep.calibration.H), [rep])
  useEffect(() => {
    let raf = 0
    const tick = () => {
      if (ref.current) onTime(ref.current.currentTime)
      raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [ref, onTime])
  const draw = useCallback(() => {
    const c = canvas.current
    const v = ref.current
    if (!c || !v) return
    const [W, H] = rep.match.image_size
    // size from the rendered video every time: the element grows once metadata loads
    const dpr = devicePixelRatio
    c.width = v.clientWidth * dpr
    c.height = v.clientHeight * dpr
    const ctx = c.getContext('2d')!
    ctx.clearRect(0, 0, c.width, c.height)
    const sx = c.width / W
    const sy = c.height / H
    const style = getComputedStyle(c) // team colours are scoped to the padel UI, not :root, inside SportLens
    ctx.font = `700 ${15 * dpr}px 'Barlow Condensed', system-ui`
    ctx.textAlign = 'center'
    rep.replay.players[idx]?.forEach((p, i) => {
      if (!p) return
      const [x, y] = toImage(rep.calibration, Hinv, p)
      if (y > H + 4) return // standing below the bottom of the frame: nothing to label on screen
      const tag = playerTag(i)
      const w = ctx.measureText(tag).width + 10 * dpr
      const ty = Math.min(y * sy + 4 * dpr, c.height - 20 * dpr)
      ctx.fillStyle = style.getPropertyValue(i < 2 ? '--team-a' : '--team-b')
      ctx.beginPath()
      ctx.roundRect(x * sx - w / 2, ty, w, 18 * dpr, 4 * dpr)
      ctx.fill()
      ctx.fillStyle = style.getPropertyValue(i < 2 ? '--team-a-ink' : '--team-b-ink') || '#fff'
      ctx.fillText(tag, x * sx, ty + 13 * dpr)
    })
    const b = rep.replay.ball_px[idx]
    if (b) {
      ctx.strokeStyle = '#ffeb3b'
      ctx.lineWidth = 2 * dpr
      ctx.beginPath()
      ctx.arc(b[0] * sx, b[1] * sy, 9 * dpr, 0, Math.PI * 2)
      ctx.stroke()
    }
  }, [idx, rep, Hinv, ref])
  useEffect(draw, [draw])
  useEffect(() => {
    const v = ref.current
    if (!v) return
    const ro = new ResizeObserver(() => draw())
    ro.observe(v)
    v.addEventListener('loadedmetadata', draw)
    return () => {
      ro.disconnect()
      v.removeEventListener('loadedmetadata', draw)
    }
  }, [draw, ref])
  return (
    <div className="video-box">
      <video ref={ref} src={src} controls preload="metadata" playsInline />
      <canvas ref={canvas} />
    </div>
  )
}

function Timeline({ rep, now, seek }: { rep: Report; now: number; seek: (t: number) => void }) {
  const D = rep.match.duration_s || 1
  return (
    <div>
      <div className="timeline" role="slider" aria-label="Match timeline" aria-valuemin={0} aria-valuemax={Math.round(D)}
        aria-valuenow={Math.round(now)} tabIndex={0}
        onKeyDown={(e) => {
          if (e.key === 'ArrowRight') seek(now + 5)
          if (e.key === 'ArrowLeft') seek(now - 5)
        }}
        onClick={(e) => {
          const r = e.currentTarget.getBoundingClientRect()
          seek(((e.clientX - r.left) / r.width) * D)
        }}>
        {rep.rallies.map((r) => (
          <div key={r.id} className={`r ${r.winner_team === 0 ? 'won-a' : r.winner_team === 1 ? 'won-b' : ''}`}
            style={{ left: `${(r.start_t / D) * 100}%`, width: `${Math.max(0.3, ((r.end_t - r.start_t) / D) * 100)}%` }}
            title={`Rally ${r.id + 1}: ${r.n_shots} shots at ${fmtTime(r.start_t)}`}
            onClick={(e) => {
              e.stopPropagation()
              seek(r.start_t)
            }} />
        ))}
        <div className="cursor" style={{ left: `${(now / D) * 100}%` }} />
      </div>
      <div className="row small secondary" style={{ justifyContent: 'space-between' }}>
        <span>Each block is a rally. Click one to jump to it.</span>
        <span className="num">{fmtTime(now)} / {fmtTime(D)}</span>
      </div>
    </div>
  )
}

// ---- players --------------------------------------------------------------------------------------------

type Row = [string, string | number]
const EMPTY = /^(–|-|0|0 \/ 0|0 \/ 0 \/ 0|0%|0 m|0 \(0 \/ 0\))$/

function detailRows(s: PlayerStats): Row[] {
  return [
    ['Serves (left / right side)', `${s.serves ?? 0} (${s.serve_side?.left ?? 0} / ${s.serve_side?.right ?? 0})`],
    ['Returns', s.returns ?? 0],
    ['Shots from net / transition / back', `${s.shots_by_zone?.net ?? 0} / ${s.shots_by_zone?.transition ?? 0} / ${s.shots_by_zone?.back ?? 0}`],
    ['Shot depth: deep / mid / short', `${s.depth?.deep ?? 0} / ${s.depth?.mid ?? 0} / ${s.depth?.short ?? 0}`],
    ['Winners / errors', `${s.winners ?? 0} / ${s.errors ?? 0}`],
    ['Ball speed to bounce, avg / max', s.ball_speed_kmh?.avg != null ? `${s.ball_speed_kmh.avg} / ${s.ball_speed_kmh.max} km/h` : '–'],
    ['Median ball speed by stroke', fmtCounts(s.ball_speed_kmh?.by_type)],
    ['Winners by stroke', fmtCounts(s.winners_by_type)],
    ['Errors by stroke', fmtCounts(s.errors_by_type)],
    ['Serve points won', s.points_served ? `${s.serve_points_won ?? 0} of ${s.points_served}` : '–'],
    ['Smashes / bandejas and víboras', `${s.overhead_kind?.smash ?? 0} / ${s.overhead_kind?.['bandeja/víbora'] ?? 0}`],
    ['Lobs', s.lobs ?? 0],
    ['Off the back glass', s.off_wall ?? 0],
    ['Hit the last shot of a rally', s.last_shot_of_rally ?? 0],
    ['Rallies involved', `${s.rally_participation_pct ?? 0}%`],
    ['Net approaches', s.net_approaches ?? 0],
    ['Distance while the ball was in play', `${s.distance_in_play_m ?? 0} m`],
    ['Work rate while the ball was in play', s.work_rate_m_per_min != null ? `${s.work_rate_m_per_min} m/min` : '–'],
  ]
}

function Players({ rep, readOnly, review }: { rep: Report; readOnly: boolean; review: Review }) {
  // a row nobody has a value for is a stat this match could not measure: leave it out rather than print dashes
  const all = rep.players.map((p) => (p.stats.serves != null ? detailRows(p.stats) : []))
  const keep = new Set((all[0] ?? []).map(([k]) => k).filter((k) => all.some((rows) => rows.some(([kk, v]) => kk === k && !EMPTY.test(String(v))))))
  return (
    <>
      <h2 className="sr-only">Players</h2>
      <div className="grid2">
        {rep.players.map((p, i) => (
          <PlayerCard key={p.id} p={p} rows={all[i].filter(([k]) => keep.has(k))} readOnly={readOnly}
            onRename={(name) => review({ players: { [p.id]: { name } } })} />
        ))}
      </div>
    </>
  )
}

function PlayerCard({ p, rows, readOnly, onRename }: { p: Player; rows: Row[]; readOnly: boolean; onRename: (name: string) => void }) {
  const s = p.stats
  const tracked = s.time_tracked_s >= 60 ? `${Math.round(s.time_tracked_s / 60)} min` : `${Math.round(s.time_tracked_s)} s`
  return (
    <article className="card player">
      <header className="player-head">
        <span className={`player-tag team-${p.team}`} style={{ background: teamColor(p.team) }}>{playerTag(p.id)}</span>
        <h3>
          {readOnly ? p.name : (
            <input className="name-input" defaultValue={p.name} aria-label={`Name of player ${playerTag(p.id)}`}
              onBlur={(e) => e.target.value !== p.name && onRename(e.target.value)} />
          )}
        </h3>
      </header>
      <dl className="kv">
        <div><dt>Distance</dt><dd className="num">{Math.round(s.distance_m)} m</dd><dd className="sub">over {tracked} tracked</dd></div>
        <div><dt>Avg speed</dt><dd className="num">{s.avg_speed_kmh ?? '–'} km/h</dd><dd className="sub">top {s.max_speed_kmh ?? '–'} km/h</dd></div>
        <div><dt>Sprints</dt><dd className="num">{s.sprints}</dd><dd className="sub">over 4 m/s for 0.5 s</dd></div>
        <div><dt>Shots</dt><dd className="num">{s.shots}</dd><dd className="sub">{s.volleys} volleys, {s.overheads} overheads</dd></div>
      </dl>
      <div>
        <h4>Court position</h4>
        <ZoneSplit z={s.zone_pct} />
      </div>
      <div className="player-split">
        <div>
          <h4>Strokes</h4>
          <Bars data={s.by_type} />
          {s.direction && (
            <>
              <h4>Shot direction</h4>
              <Bars data={s.direction} />
            </>
          )}
          {s.padel_types && Object.keys(s.padel_types).length > 0 && (
            <>
              <h4>Padel shots</h4>
              <Bars data={s.padel_types} />
            </>
          )}
        </div>
        <div>
          <h4>Where they stood</h4>
          <Heatmap grid={p.heatmap} size={170} id={`heat-${p.id}`} />
        </div>
      </div>
      {rows.length > 0 && (
        <table className="details small">
          <tbody>
            {rows.map(([k, v]) => (
              <tr key={k}><th scope="row">{k}</th><td className="num">{v}</td></tr>
            ))}
          </tbody>
        </table>
      )}
    </article>
  )
}

function fmtOf(v: unknown, key: string): string {
  const o = v as Record<string, number> | undefined
  return o && o.of ? `${o[key]} of ${o.of}` : '–'
}

function fmtCounts(v: Record<string, number> | undefined): string {
  const e = Object.entries(v ?? {}).filter(([, n]) => n > 0)
  return e.length ? e.map(([k, n]) => `${k} ${n}`).join(', ') : '–'
}

// ---- pairs ----------------------------------------------------------------------------------------------

function Pairs({ rep, names, readOnly, review, seek }: {
  rep: Report; names: string[]; readOnly: boolean; review: Review; seek: (t: number) => void
}) {
  const rowsOf = (st: Record<string, unknown>): Row[] => {
    const nf = st.net_finishes as Record<string, number> | undefined
    const r: Row[] = [
      ['Distance covered (pair)', st.distance_m != null ? `${Math.round(Number(st.distance_m))} m` : '–'],
      ['Shots', Number(st.shots ?? 0)],
      ['Both at the net', st.both_at_net_pct != null ? `${st.both_at_net_pct}%` : '–'],
      ['Both back', st.both_back_pct != null ? `${st.both_back_pct}%` : '–'],
      ['Average partner distance', st.avg_partner_distance_m != null ? `${st.avg_partner_distance_m} m` : '–'],
      ['Average side-to-side spacing', st.avg_lateral_spacing_m != null ? `${st.avg_lateral_spacing_m} m` : '–'],
      ['Average front-to-back offset', st.avg_depth_offset_m != null ? `${st.avg_depth_offset_m} m` : '–'],
      ['Hit the last shot of a rally', Number(st.last_shot_in_rallies ?? 0)],
      ['Points won', st.points_won != null ? `${st.points_won} (${st.points_won_pct ?? '–'}%)` : '–'],
      ['Games won / held / breaks', `${st.games_won ?? 0} / ${st.service_games_held ?? 0} / ${st.breaks ?? 0}`],
      ['Serve / return points won', st.serve_points_won_pct != null ? `${st.serve_points_won_pct}% / ${st.return_points_won_pct ?? '–'}%` : '–'],
      ['Winners / errors', `${st.winners ?? 0} / ${st.errors ?? 0}`],
      ['Break points won', fmtOf(st.break_points, 'won')],
      ['Break points saved', fmtOf(st.break_points_saved, 'saved')],
      ['Points finished at the net (won / lost)', `${nf?.won ?? 0} / ${nf?.lost ?? 0}`],
      ...(st.golden_points ? [['Golden points won', fmtOf(st.golden_points, 'won')] as Row] : []),
      ...pairExtra(st),
    ]
    return r
  }
  const all = rep.teams.map((t) => rowsOf(t.stats))
  const keep = new Set((all[0] ?? []).map(([k]) => k).filter((k) => all.some((rows) => rows.some(([kk, v]) => kk === k && !EMPTY.test(String(v))))))
  return (
    <>
      <h2 className="sr-only">Pairs</h2>
      <div className="grid2">
        {rep.teams.map((t, i) => (
          <article className="card stack" key={t.id}>
            <header className="player-head">
              <span className={`player-tag team-${t.id}`} style={{ background: teamColor(t.id) }}>{t.id === 0 ? 'A' : 'B'}</span>
              <h3>
                {readOnly ? t.name : (
                  <input className="name-input" defaultValue={t.name} aria-label={`Name of ${t.name}`}
                    onBlur={(e) => e.target.value !== t.name && review({ teams: { [t.id]: { name: e.target.value } } })} />
                )}
              </h3>
              <span className="secondary small">{t.players.map((p) => names[p]).join(' and ')}</span>
            </header>
            <table className="details small">
              <tbody>
                {all[i].filter(([k]) => keep.has(k)).map(([k, v]) => (
                  <tr key={k}><th scope="row">{k}</th><td className="num">{v}</td></tr>
                ))}
              </tbody>
            </table>
            <h4>Where they hit from</h4>
            <Court height={300} marks={rep.shots.filter((s) => s.team === t.id && s.pos_m && !s.deleted).map((s) => ({
              p: s.pos_m!, team: s.team, title: `${fmtTime(s.t)} ${names[s.player]}: ${s.type}`, onClick: () => seek(s.t - 1),
            }))} />
          </article>
        ))}
      </div>
    </>
  )
}

function pairExtra(st: Record<string, unknown>): Row[] {
  const f = st.formation_pct as Record<string, number> | undefined
  const d = st.direction as Record<string, number> | undefined
  const rows: Row[] = []
  if (f) {
    rows.push(['Attacking (both at the net)', `${f.attack_both_net}%`])
    rows.push(['Defending (both back)', `${f.defence_both_back}%`])
    rows.push(['Split (one up, one back)', `${f.split_one_up_one_back}%`])
  }
  if (st.net_control_pct != null) rows.push(['Net control (at least one at the net)', `${st.net_control_pct}%`])
  if (st.rallies_served != null) rows.push(['Rallies served', st.rallies_served as number])
  if (st.avg_time_to_net_after_serve_s != null) rows.push(['Time to the net after their serve', `${st.avg_time_to_net_after_serve_s} s`])
  if (d) rows.push(['Crosscourt / down the line / centre', `${d.crosscourt} / ${d['down the line']} / ${d.centre}`])
  return rows
}

// ---- rallies, shots, quality ----------------------------------------------------------------------------

function Rallies({ rep, names, seek, review, readOnly }: {
  rep: Report; names: string[]; seek: (t: number) => void; review: Review; readOnly: boolean
}) {
  return (
    <div className="card stack">
      <h2 className="sr-only">Rallies</h2>
      {rep.match.rally_length_distribution && (
        <div style={{ maxWidth: 420 }}>
          <h3>Rally length in shots</h3>
          <Bars data={rep.match.rally_length_distribution} />
        </div>
      )}
      <div className="table-scroll">
        <table>
          <thead><tr><th>#</th><th>Start</th><th className="num">Shots</th><th className="num">Length</th><th>Opened with</th><th>Last shot by</th><th>Point to</th></tr></thead>
          <tbody>
            {rep.rallies.map((r) => (
              <tr key={r.id} className="clickable" onClick={() => seek(r.start_t)}>
                <td className="num">{r.id + 1}</td>
                <td className="num">{fmtTime(r.start_t)}</td>
                <td className="num">{r.n_shots}</td>
                <td className="num">{r.duration_s} s</td>
                <td>{r.first_type ?? '–'}</td>
                <td>{r.last_player != null ? names[r.last_player] : '–'}</td>
                <td onClick={(e) => e.stopPropagation()}>
                  {readOnly ? (
                    r.winner_source === 'confirmed' && r.winner_team != null ? rep.teams[r.winner_team]?.name : <span className="secondary">not set</span>
                  ) : (
                    <>
                      <select value={r.winner_team ?? ''} aria-label={`Winner of rally ${r.id + 1}`}
                        onChange={(e) => review({ rallies: { [r.id]: { winner_team: e.target.value === '' ? null : Number(e.target.value) } } })}>
                        <option value="">not set</option>
                        {rep.teams.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
                      </select>
                      {r.winner_source === 'estimated' && <span className="small secondary"> guess, {Math.round((r.winner_conf ?? 0) * 100)}% sure</span>}
                    </>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function Shots({ rep, names, seek, review, now, readOnly }: {
  rep: Report; names: string[]; seek: (t: number) => void; review: Review; now: number; readOnly: boolean
}) {
  const [who, setWho] = useState<number | ''>('')
  const [kind, setKind] = useState('')
  const kinds = Object.keys(rep.match.type_mix)
  const list = rep.shots.filter((s: Shot) => !s.deleted && (who === '' || s.player === who) && (!kind || s.type === kind))
  const anyPadel = rep.shots.some((s) => s.padel_type)
  const anySpeed = rep.shots.some((s) => s.speed_kmh)
  return (
    <div className="card stack">
      <h2 className="sr-only">Shots</h2>
      <div className="row">
        <select value={who} aria-label="Filter by player" onChange={(e) => setWho(e.target.value === '' ? '' : Number(e.target.value))}>
          <option value="">All players</option>
          {names.map((n, i) => <option key={i} value={i}>{n}</option>)}
        </select>
        <select value={kind} aria-label="Filter by stroke" onChange={(e) => setKind(e.target.value)}>
          <option value="">All strokes</option>
          {kinds.map((k) => <option key={k}>{k}</option>)}
        </select>
        <span className="secondary small">{list.length} shots. Click a row to watch it.</span>
      </div>
      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              <th>Time</th><th className="num">Rally</th><th>Player</th><th>Stroke</th>
              {anyPadel && <th>Padel shot</th>}<th>Tags</th>
              {anySpeed && <th className="num" title="Average ball speed from the racket to its first bounce (estimated)">Speed</th>}
              {!readOnly && <th><span className="sr-only">Actions</span></th>}
            </tr>
          </thead>
          <tbody>
            {list.map((s) => (
              <tr key={s.id} className={`clickable ${Math.abs(s.t - now) < 0.4 ? 'active' : ''}`} onClick={() => seek(s.t - 1)}>
                <td className="num">{fmtTime(s.t)}</td>
                <td className="num">{s.rally + 1}</td>
                <td><span className="team-chip"><i style={{ background: teamColor(s.team) }} />{names[s.player]}</span></td>
                <td onClick={readOnly ? undefined : (e) => e.stopPropagation()}>
                  {readOnly ? s.type : (
                    <select value={s.type} aria-label={`Stroke at ${fmtTime(s.t)}`} onChange={(e) => review({ shots: { [s.id]: { type: e.target.value } } })}>
                      {kinds.map((k) => <option key={k}>{k}</option>)}
                    </select>
                  )}{' '}
                  <span className="small secondary">{s.label === 'confirmed' ? 'confirmed' : `${Math.round(s.type_conf * 100)}% sure`}</span>
                </td>
                {anyPadel && <td>{s.padel_type ? <>{s.padel_type} <span className="small secondary">{Math.round((s.padel_type_conf ?? 0) * 100)}%</span></> : <span className="secondary">–</span>}</td>}
                <td>{s.volley && <span className="tag">volley</span>}{s.overhead && <span className="tag">overhead</span>}</td>
                {anySpeed && <td className="num">{s.speed_kmh ? `${Math.round(s.speed_kmh)} km/h` : '–'}</td>}
                {!readOnly && (
                  <td onClick={(e) => e.stopPropagation()}>
                    <button className="ghost small" title="This was not a shot: remove it" onClick={() => review({ shots: { [s.id]: { deleted: true } } })}>Remove</button>
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function Quality({ rep }: { rep: Report }) {
  const q = rep.quality as Record<string, unknown>
  const pct = (k: string) => (typeof q[k] === 'number' ? `${q[k]}%` : null)
  const rows: [string, string | null, string][] = [
    ['Players tracked', pct('players_tracked_pct'), 'Share of frames in which each player was located on the court.'],
    ['Ball seen', pct('ball_observed_pct'), 'Share of frames in which the ball was detected. The ball is small and often blurred on club cameras.'],
    ['Ball path covered', pct('ball_track_pct'), 'Share of frames with a ball position after joining detections into flight paths.'],
    ['Court calibration', typeof q.calibration_reproj_m === 'number' ? `${Math.round((q.calibration_reproj_m as number) * 100)} cm average error` : null,
      'How closely the marked court lines match the real court. Distances and positions inherit this error.'],
    ['Out of camera view', typeof q.view_limit_y === 'number' ? `last ${(20 - (q.view_limit_y as number)).toFixed(1)} m before the near back wall` : null,
      'Players standing deeper than this on the near side are below the bottom of the frame and cannot be tracked there.'],
    ['Hit detection', q.audio_used ? `video and sound${typeof q.audio_hits === 'number' && q.audio_hits > 0 ? ` (${q.audio_hits} hits heard)` : ''}` : 'video only', 'Signals used to find the moment of each shot.'],
    ['Player identity', q.identity_linked ? 'kept when players change ends' : 'per segment', 'Whether each player keeps the same tag across the whole video.'],
    ['Processing time', typeof q.analysis_s === 'number' ? `${Math.round((q.analysis_s as number) / 60)} min` : null, 'Time the analysis took.'],
  ]
  return (
    <div className="card">
      <h2 className="sr-only">About this analysis</h2>
      <table className="details">
        <tbody>
          {rows.filter(([, v]) => v != null).map(([k, v, help]) => (
            <tr key={k}>
              <th scope="row">{k}<span className="help">{help}</span></th>
              <td className="num">{v}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
