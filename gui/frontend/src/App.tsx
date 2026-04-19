import { NavLink, Route, Routes } from 'react-router-dom'
import { AuthorFilters } from './pages/AuthorFilters'
import { Home } from './pages/Home'
import { PaperDetail } from './pages/PaperDetail'
import { PastRuns } from './pages/PastRuns'
import { Preferences } from './pages/Preferences'
import { Rankings } from './pages/Rankings'

const nav = [
  { to: '/', label: 'Home', end: true },
  { to: '/profile', label: 'VC Preferences' },
  { to: '/filters', label: 'Author Filters' },
  { to: '/rankings/latest', label: 'Rankings' },
  { to: '/runs', label: 'Past Runs' },
]

export default function App() {
  return (
    <div className="layout">
      <aside className="sidebar">
        <h1>Ventura Flow</h1>
        <nav className="nav">
          {nav.map((n) => (
            <NavLink
              key={n.to}
              to={n.to}
              end={n.end}
              className={({ isActive }) => (isActive ? 'active' : '')}
            >
              {n.label}
            </NavLink>
          ))}
        </nav>
      </aside>

      <main className="main">
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/profile" element={<Preferences />} />
          <Route path="/filters" element={<AuthorFilters />} />
          <Route path="/rankings/:runId" element={<Rankings />} />
          <Route path="/runs" element={<PastRuns />} />
          <Route path="/runs/:runId/paper/:paperId" element={<PaperDetail />} />
          <Route path="*" element={<div>Not found.</div>} />
        </Routes>
      </main>
    </div>
  )
}
