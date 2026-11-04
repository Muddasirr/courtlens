import { useState, type FormEvent } from 'react'
import { core, type User } from '../lib/session'

export default function Login({ onSignedIn }: { onSignedIn: (u: User) => void }) {
  const [mode, setMode] = useState<'in' | 'up'>('in')
  const [email, setEmail] = useState('')
  const [name, setName] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  async function submit(e: FormEvent) {
    e.preventDefault()
    setError('')
    setBusy(true)
    try {
      if (mode === 'up') await core.register(email, name, password)
      await core.login(email, password)
      onSignedIn(await core.me())
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="auth">
      <div className="auth-card">
        <div className="shell-brand big">
          <span className="shell-mark" aria-hidden="true" />
          SportLens
        </div>
        <p className="muted">Match analytics for futsal and padel facilities.</p>
        <form onSubmit={submit} className="stack">
          <label>
            Email
            <input type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
          </label>
          {mode === 'up' && (
            <label>
              Full name
              <input required value={name} onChange={(e) => setName(e.target.value)} />
            </label>
          )}
          <label>
            Password
            <input
              type="password"
              required
              minLength={mode === 'up' ? 8 : undefined}
              autoComplete={mode === 'up' ? 'new-password' : 'current-password'}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </label>
          {error && <p className="notice error">{error}</p>}
          <button className="btn primary" disabled={busy}>
            {busy ? 'Please wait…' : mode === 'in' ? 'Sign in' : 'Create account'}
          </button>
        </form>
        <button type="button" className="btn link" onClick={() => setMode(mode === 'in' ? 'up' : 'in')}>
          {mode === 'in' ? 'New here? Create an account' : 'Have an account? Sign in'}
        </button>
      </div>
    </div>
  )
}
