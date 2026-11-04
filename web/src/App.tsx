import { lazy, Suspense, useEffect, useState, type ReactNode } from 'react'
import { BrowserRouter, Navigate, NavLink, Outlet, Route, Routes, useLocation, useNavigate, useParams } from 'react-router-dom'
import { core, getToken, setActiveFacility, signOut, type Facility, type User } from './lib/session'
import Facilities from './pages/Facilities'
import Login from './pages/Login'
import Overview from './pages/Overview'
import Players from './pages/Players'

// Sport UIs are separate chunks: loaded on first visit to that sport.
const futsal = () => import('./sports/Futsal')
const FutsalHome = lazy(() => futsal().then((m) => ({ default: m.FutsalHome })))
const FutsalMatch = lazy(() => futsal().then((m) => ({ default: m.FutsalMatch })))
const FutsalLabel = lazy(() => futsal().then((m) => ({ default: m.FutsalLabel })))
const FutsalShare = lazy(() => futsal().then((m) => ({ default: m.FutsalShare })))
const FutsalPhase0 = lazy(() => futsal().then((m) => ({ default: m.FutsalPhase0 })))
const Padel = lazy(() => import('./sports/Padel'))
const PadelShare = lazy(() => import('./sports/Padel').then((m) => ({ default: m.PadelShare })))

type Session = { ready: boolean; user: User | null }

function useSession(): [Session, (u: User | null) => void] {
  const [s, set] = useState<Session>({ ready: !getToken(), user: null })
  useEffect(() => {
    if (!getToken()) return
    core
      .me()
      .then((user) => set({ ready: true, user }))
      .catch(() => set({ ready: true, user: null }))
  }, [])
  return [s, (user) => set({ ready: true, user })]
}

const Loading = () => <p className="muted pad">Loading…</p>

function FacilityLayout({ user }: { user: User }) {
  const { facilityId = '' } = useParams()
  const navigate = useNavigate()
  const [facilities, setFacilities] = useState<Facility[]>([])
  // padel files new uploads under the active facility; set before children render
  setActiveFacility(facilityId)
  useEffect(() => {
    core.facilities().then(setFacilities).catch(() => setFacilities([]))
  }, [])
  const { pathname } = useLocation()
  const tab = ({ isActive }: { isActive: boolean }) => (isActive ? 'nav-link active' : 'nav-link')
  // futsal match pages live at /facilities/:id/matches/... (CourtLens' own paths) but belong to the Futsal tab
  const futsalTab = ({ isActive }: { isActive: boolean }) => tab({ isActive: isActive || pathname.includes('/matches/') })
  return (
    <div className="shell">
      <header className="shell-bar">
        <NavLink to="/" className="shell-brand" aria-label="SportLens home">
          <span className="shell-mark" aria-hidden="true" />
          SportLens
        </NavLink>
        <select
          className="facility-select"
          aria-label="Facility"
          value={facilityId}
          onChange={(e) => navigate(`/facilities/${e.target.value}`)}
        >
          {!facilities.some((f) => f.id === facilityId) && <option value={facilityId}>…</option>}
          {facilities.map((f) => (
            <option key={f.id} value={f.id}>
              {f.name}
            </option>
          ))}
        </select>
        <nav className="shell-nav" aria-label="Sections">
          <NavLink end to={`/facilities/${facilityId}`} className={tab}>
            Overview
          </NavLink>
          <NavLink to={`/facilities/${facilityId}/futsal`} className={futsalTab}>
            Futsal
          </NavLink>
          <NavLink to={`/facilities/${facilityId}/padel`} className={tab}>
            Padel
          </NavLink>
          <NavLink to={`/facilities/${facilityId}/players`} className={tab}>
            Players
          </NavLink>
        </nav>
        <div className="shell-user">
          <span className="muted" title={user.email}>
            {user.full_name || user.email}
          </span>
          <button type="button" className="btn ghost" onClick={signOut}>
            Sign out
          </button>
        </div>
      </header>
      <Suspense fallback={<Loading />}>
        <Outlet />
      </Suspense>
    </div>
  )
}

function Guard({ user, children }: { user: User | null; children: ReactNode }) {
  return user ? <>{children}</> : <Navigate to="/" replace />
}

function Routed() {
  const [session, setUser] = useSession()
  const navigate = useNavigate()
  if (!session.ready) return <Loading />
  const user = session.user
  return (
    <Routes>
      {/* public share report: no sign-in, revoked tokens 404 */}
      <Route
        path="/report/:shareToken"
        element={
          <Suspense fallback={<Loading />}>
            <FutsalShare />
          </Suspense>
        }
      />
      <Route
        path="/share/padel/:token"
        element={
          <Suspense fallback={<Loading />}>
            <PadelShare />
          </Suspense>
        }
      />
      <Route
        path="/"
        element={
          user ? (
            <Facilities user={user} />
          ) : (
            <Login
              onSignedIn={(u) => {
                setUser(u)
                navigate('/')
              }}
            />
          )
        }
      />
      <Route
        path="/phase0"
        element={
          <Guard user={user}>
            <Suspense fallback={<Loading />}>
              <FutsalPhase0 />
            </Suspense>
          </Guard>
        }
      />
      <Route
        path="/facilities/:facilityId"
        element={
          <Guard user={user}>
            <FacilityLayout user={user!} />
          </Guard>
        }
      >
        <Route index element={<Overview />} />
        <Route path="players" element={<Players />} />
        <Route path="futsal" element={<FutsalHome />} />
        <Route path="padel" element={<Padel />} />
        {/* futsal match routes keep CourtLens' paths, so its in-page links keep working */}
        <Route path="matches/:matchId" element={<FutsalMatch />} />
        <Route path="matches/:matchId/label" element={<FutsalLabel />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}

export default function App() {
  return (
    <BrowserRouter>
      <Routed />
    </BrowserRouter>
  )
}
