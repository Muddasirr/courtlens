// Padel UI = the PadelLens web app (../padel/web/src). Its pages navigate with hash routes
// (#/, #/m/<id>/calibrate, #/m/<id>), so the shell mounts it at /facilities/:id/padel and leaves the hash to it.
import '@padel/styles.css'
import Calibrate from '@padel/pages/Calibrate'
import Matches from '@padel/pages/Matches'
import ReportPage from '@padel/pages/Report'
import { links } from '@padel/api'
import { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { refreshPadelMediaToken } from '../lib/session'

// share links open the public SportLens route, not the padel app's own hash route
links.share = (token: string) => `${window.location.origin}/share/padel/${token}`

function useHash(): string[] {
  const read = () => window.location.hash.replace(/^#\/?/, '').split('/').filter(Boolean)
  const [parts, setParts] = useState(read)
  useEffect(() => {
    const on = () => setParts(read())
    window.addEventListener('hashchange', on)
    return () => window.removeEventListener('hashchange', on)
  }, [])
  return parts
}

export default function PadelSection() {
  const parts = useHash()
  const [media, setMedia] = useState<'loading' | 'ok' | string>('loading')
  useEffect(() => {
    refreshPadelMediaToken()
      .then(() => setMedia('ok'))
      .catch((e: Error) => setMedia(e.message || 'padel service unavailable'))
  }, [])
  if (media === 'loading') return <p className="muted pad">Connecting to the padel service…</p>
  if (media !== 'ok')
    return (
      <div className="notice error pad">
        <strong>Padel service unavailable.</strong> {media}
      </div>
    )
  let page = <Matches />
  if (parts[0] === 'm' && parts[1]) page = parts[2] === 'calibrate' ? <Calibrate id={parts[1]} /> : <ReportPage id={parts[1]} />
  return (
    <div className="sl-padel sport-scope">
      <main className="wrap">{page}</main>
    </div>
  )
}

/** Public, read-only padel report (no sign-in): /share/padel/:token */
export function PadelShare() {
  const { token = '' } = useParams()
  return (
    <div className="sl-padel sport-scope public-report">
      <header className="public-bar">
        <span className="shell-brand"><span className="shell-mark" aria-hidden="true" />SportLens</span>
        <span className="muted small">Padel match report</span>
      </header>
      <main className="wrap">
        <ReportPage shareToken={token} />
      </main>
    </div>
  )
}
