/** Small single-series charts: labelled bars, zone split, folded heatmap. Text uses ink tokens;
 *  the only colour carriers are the marks. */

export function Bars({ data, unit = '' }: { data: Record<string, number>; unit?: string }) {
  const max = Math.max(1, ...Object.values(data))
  return (
    <div className="bars" role="table">
      {Object.entries(data).map(([k, v]) => (
        <div className="bar-row" key={k} role="row" title={`${k}: ${v}${unit}`}>
          <span className="secondary" role="cell">{k}</span>
          <div className="track"><div className="fill" style={{ width: `${(v / max) * 100}%`, minWidth: v ? 4 : 0 }} /></div>
          <span className="num" role="cell" style={{ textAlign: 'right' }}>{v}{unit}</span>
        </div>
      ))}
    </div>
  )
}

const ZONES: [keyof Zones, string, string][] = [
  ['net', 'Net', 'var(--seq-2)'],
  ['transition', 'Transition', 'var(--seq-1)'],
  ['back', 'Back', 'var(--seq-0)'],
]
interface Zones { net: number | null; transition: number | null; back: number | null }

/** Ordered 3-step split (net -> back) with direct labels so the steps never rely on colour alone. */
export function ZoneSplit({ z }: { z: Zones }) {
  return (
    <div>
      <div className="zone-bar">
        {ZONES.map(([k, label, c]) => (
          <span key={k} style={{ width: `${z[k] ?? 0}%`, background: c }} title={`${label}: ${z[k] ?? 0}%`} />
        ))}
      </div>
      <div className="row small secondary" style={{ marginTop: 4, gap: 10 }}>
        {ZONES.map(([k, label]) => (
          <span key={k}>{label} <b className="num" style={{ color: 'var(--text-primary)' }}>{z[k] ?? 0}%</b></span>
        ))}
      </div>
    </div>
  )
}

/** Sports-broadcast heat scale: lime (little time) -> yellow -> orange -> red (most time). */
const HEAT: [number, [number, number, number]][] = [
  [0, [163, 230, 53]],
  [0.35, [250, 204, 21]],
  [0.65, [249, 115, 22]],
  [1, [239, 68, 68]],
]
export function heatColor(t: number): string {
  const x = Math.max(0, Math.min(1, t))
  let k = 0
  while (k < HEAT.length - 2 && x > HEAT[k + 1][0]) k++
  const [a, ca] = HEAT[k]
  const [b, cb] = HEAT[k + 1]
  const f = (x - a) / (b - a || 1)
  const c = ca.map((v, i) => Math.round(v + (cb[i] - v) * f))
  return `rgb(${c[0]} ${c[1]} ${c[2]})`
}
const HEAT_CSS = `linear-gradient(90deg, ${[0, 0.35, 0.65, 1].map((t) => heatColor(t)).join(', ')})`

/** Occupancy on the player's own half: net at the top, back wall at the bottom, seen from behind the player.
 *  Drawn the way broadcasters do: blurred heat over the green court, white lines on top. */
export function Heatmap({ grid, size = 200, id = 'h' }: { grid: number[][]; size?: number; id?: string }) {
  if (!grid.length) return <div className="muted small">No position data</div>
  const rows = grid.length
  const cols = grid[0].length
  const max = Math.max(...grid.flat()) || 1
  const svc = rows * (6.95 / 10)
  return (
    <figure className="heat">
      <svg viewBox={`0 0 ${cols} ${rows}`} style={{ width: size, height: (size * rows) / cols }} role="img"
        aria-label="Where the player stood on their half: red is most time, lime least">
        <defs>
          <filter id={`${id}-blur`} x="-10%" y="-10%" width="120%" height="120%">
            <feGaussianBlur stdDeviation={0.55} />
          </filter>
          <clipPath id={`${id}-clip`}><rect width={cols} height={rows} /></clipPath>
        </defs>
        <rect width={cols} height={rows} fill="var(--court)" />
        <g filter={`url(#${id}-blur)`} clipPath={`url(#${id}-clip)`}>
          {grid.map((r, i) =>
            r.map((v, j) => {
              const t = Math.sqrt(v / max)
              return t > 0.3 ? (
                <rect key={`${i}-${j}`} x={j - 0.15} y={i - 0.15} width={1.3} height={1.3} fill={heatColor(t)}
                  fillOpacity={0.35 + 0.6 * t}>
                  <title>{`${(i * 0.5).toFixed(1)}–${(i * 0.5 + 0.5).toFixed(1)} m from the net: ${(v * 100).toFixed(1)}% of the time`}</title>
                </rect>
              ) : null
            }),
          )}
        </g>
        <g stroke="var(--court-line)" strokeWidth={0.12} fill="none" opacity={0.9}>
          <line x1={0} y1={svc} x2={cols} y2={svc} />
          <line x1={cols / 2} y1={0} x2={cols / 2} y2={svc} />
        </g>
        <line x1={0} y1={0.15} x2={cols} y2={0.15} stroke="var(--court-line)" strokeWidth={0.3} />
      </svg>
      <figcaption className="heat-legend">
        <span>Net at the top</span>
        <span className="heat-scale"><i>less</i><b style={{ background: HEAT_CSS }} /><i>more</i></span>
      </figcaption>
    </figure>
  )
}
