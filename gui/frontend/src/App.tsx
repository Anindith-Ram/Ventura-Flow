import { AnimatePresence, motion } from 'framer-motion'
import { BarChart3, History, Home as HomeIcon, Settings, Sliders, Sparkles, Star } from 'lucide-react'
import { NavLink, Route, Routes, useLocation } from 'react-router-dom'
import { AuthorFilters } from './pages/AuthorFilters'
import { Home } from './pages/Home'
import { PaperDetail } from './pages/PaperDetail'
import { PastRuns } from './pages/PastRuns'
import { Preferences } from './pages/Preferences'
import { Rankings } from './pages/Rankings'
import { Watchlist } from './pages/Watchlist'
import { useProfile } from './store'

const nav = [
  { to: '/', label: 'Home', icon: HomeIcon, end: true },
  { to: '/profile', label: 'Preferences', icon: Settings },
  { to: '/filters', label: 'Weights', icon: Sliders },
  { to: '/rankings/latest', label: 'Rankings', icon: BarChart3 },
  { to: '/watchlist', label: 'Watchlist', icon: Star },
  { to: '/runs', label: 'Past Runs', icon: History },
]

function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean)
  if (!parts.length) return '—'
  return (parts[0][0] + (parts[1]?.[0] ?? '')).toUpperCase()
}

function TopNav() {
  const { profile } = useProfile()
  const name = profile?.user_name || ''
  const firm = profile?.firm_name || ''

  return (
    <header className="topnav">
      <div className="brand">
        <div className="logo"><Sparkles size={16} strokeWidth={2.5} /></div>
        Ventura Flow
      </div>
      <nav className="links">
        {nav.map((n) => {
          const Icon = n.icon
          return (
            <NavLink
              key={n.to}
              to={n.to}
              end={n.end}
              className={({ isActive }) => (isActive ? 'active' : '')}
            >
              <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
                <Icon size={14} strokeWidth={2} />
                {n.label}
              </span>
            </NavLink>
          )
        })}
      </nav>
      {name && (
        <div className="user" title={firm || undefined}>
          <span className="avatar">{initials(name)}</span>
          <span>{name.split(' ')[0]}</span>
        </div>
      )}
    </header>
  )
}

function AnimatedRoutes() {
  const location = useLocation()
  return (
    <AnimatePresence mode="wait">
      <motion.div
        key={location.pathname}
        initial={{ opacity: 0, y: 6 }}
        animate={{ opacity: 1, y: 0 }}
        exit={{ opacity: 0, y: -4 }}
        transition={{ duration: 0.2, ease: [0.22, 1, 0.36, 1] }}
      >
        <Routes location={location}>
          <Route path="/" element={<Home />} />
          <Route path="/profile" element={<Preferences />} />
          <Route path="/filters" element={<AuthorFilters />} />
          <Route path="/rankings/:runId" element={<Rankings />} />
          <Route path="/runs" element={<PastRuns />} />
          <Route path="/watchlist" element={<Watchlist />} />
          <Route path="/runs/:runId/paper/:paperId" element={<PaperDetail />} />
          <Route path="*" element={<div>Not found.</div>} />
        </Routes>
      </motion.div>
    </AnimatePresence>
  )
}

export default function App() {
  return (
    <div className="layout">
      <TopNav />
      <main className="main">
        <AnimatedRoutes />
      </main>
    </div>
  )
}
