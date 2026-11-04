import { useEffect, useState, type FormEvent } from 'react'
import { Link, Navigate } from 'react-router-dom'
import { core, signOut, type Facility, type User } from '../lib/session'

export default function Facilities({ user }: { user: User }) {
  const [facilities, setFacilities] = useState<Facility[] | null>(null)
  const [name, setName] = useState('')
  const [error, setError] = useState('')

  const load = () => core.facilities().then(setFacilities).catch((e: Error) => setError(e.message))
  useEffect(() => {
    void load()
  }, [])

  async function create(e: FormEvent) {
    e.preventDefault()
    try {
      await core.createFacility(name)
      setName('')
      await load()
    } catch (err) {
      setError((err as Error).message)
    }
  }

  if (facilities?.length === 1) return <Navigate to={`/facilities/${facilities[0].id}`} replace />
  return (
    <div className="auth">
      <div className="auth-card wide">
        <div className="row between">
          <div className="shell-brand big">
            <span className="shell-mark" aria-hidden="true" />
            SportLens
          </div>
          <button type="button" className="btn ghost" onClick={signOut}>
            Sign out
          </button>
        </div>
        <h1>Your facilities</h1>
        <p className="muted">Signed in as {user.email}. A facility holds your courts, staff, futsal and padel matches.</p>
        {error && <p className="notice error">{error}</p>}
        {facilities === null ? (
          <p className="muted">Loading…</p>
        ) : facilities.length === 0 ? (
          <p className="muted">No facility yet. Create the first one to start uploading matches.</p>
        ) : (
          <ul className="card-list">
            {facilities.map((f) => (
              <li key={f.id}>
                <Link to={`/facilities/${f.id}`}>{f.name}</Link>
                <span className="muted">{f.timezone}</span>
              </li>
            ))}
          </ul>
        )}
        <form className="row" onSubmit={create}>
          <input placeholder="New facility name" required value={name} onChange={(e) => setName(e.target.value)} />
          <button className="btn primary">Create</button>
        </form>
      </div>
    </div>
  )
}
