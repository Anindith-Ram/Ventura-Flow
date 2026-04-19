import { motion } from 'framer-motion'
import { ArrowRight, BarChart3, History, Play, Settings, Sliders, Square } from 'lucide-react'
import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api'
import { PipelineStages } from '../components/PipelineStages'
import { useEventStream, useProfile, useRunStatus } from '../store'

function OnboardModal({ onSave }: { onSave: (name: string, firm: string) => void }) {
  const [name, setName] = useState('')
  const [firm, setFirm] = useState('')
  return (
    <div className="modal-backdrop">
      <div className="modal">
        <h2>Welcome to Ventura Flow</h2>
        <p>
          An agentic research pipeline for finding investable breakthroughs in academic papers.
          Let's set up your profile so we can greet you properly.
        </p>
        <label>Your name</label>
        <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Ada Lovelace" autoFocus />
        <label>Firm name (optional)</label>
        <input value={firm} onChange={(e) => setFirm(e.target.value)} placeholder="Analytical Engines Capital" />
        <div style={{ marginTop: 20, display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
          <button
            className="primary"
            disabled={!name.trim()}
            onClick={() => onSave(name.trim(), firm.trim())}
          >
            Continue <ArrowRight size={14} strokeWidth={2.5} style={{ marginLeft: 4, verticalAlign: 'middle' }} />
          </button>
        </div>
      </div>
    </div>
  )
}

export function Home() {
  const nav = useNavigate()
  const { events, activeRunId } = useEventStream()
  const active = useRunStatus()
  const { profile, save, loading } = useProfile()

  const [mode, setMode] = useState<'single' | 'autonomous'>('single')
  const [timeLimit, setTimeLimit] = useState(60)
  const [paperCap, setPaperCap] = useState(200)
  const [maxQueries, setMaxQueries] = useState(6)
  const [papersPerQuery, setPapersPerQuery] = useState(20)
  const [topK, setTopK] = useState(5)
  const [starting, setStarting] = useState(false)

  const needsOnboarding = !loading && profile && !profile.user_name

  const greeting = useMemo(() => {
    const h = new Date().getHours()
    if (h < 5) return 'Working late'
    if (h < 12) return 'Good morning'
    if (h < 18) return 'Good afternoon'
    return 'Good evening'
  }, [])

  const firstName = profile?.user_name.split(' ')[0] ?? ''

  async function handleOnboard(name: string, firm: string) {
    if (!profile) return
    await save({ ...profile, user_name: name, firm_name: firm })
  }

  async function handleStart() {
    setStarting(true)
    try {
      await api.startRun({
        mode,
        max_queries: maxQueries,
        papers_per_query: papersPerQuery,
        bull_bear_for_top_k: topK,
        autonomous_time_limit_minutes: timeLimit,
        autonomous_paper_cap: paperCap,
      })
    } catch (e: any) {
      alert(`Failed to start: ${e.message}`)
    } finally {
      setStarting(false)
    }
  }

  async function handleCancel() {
    if (!confirm('Cancel the active run?')) return
    await api.cancelRun()
  }

  const activeEvents = events.filter((e) => !activeRunId || e.run_id === activeRunId)

  return (
    <div>
      {needsOnboarding && <OnboardModal onSave={handleOnboard} />}

      {/* ── Hero ── */}
      <motion.div
        className="hero"
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.4, ease: [0.22, 1, 0.36, 1] }}
      >
        <div className="greet">
          {greeting}
        </div>
        <h1>
          {firstName ? <>Welcome back, <span className="accent">{firstName}</span>.</> : <>Find the <span className="accent">next breakthrough</span>.</>}
        </h1>
        <p>
          Your agents read the academic literature, weigh every paper against your thesis,
          and surface the ones worth a partner meeting. Configure a run below or pick up where you left off.
        </p>
        <div className="cta">
          <button
            className="primary"
            disabled={active || starting}
            onClick={handleStart}
            style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}
          >
            <Play size={14} strokeWidth={2.5} />
            {starting ? 'Starting…' : active ? 'Run in progress…' : 'Start a new run'}
          </button>
          {active && (
            <button className="danger" onClick={handleCancel} style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
              <Square size={13} strokeWidth={2.5} />
              Cancel
            </button>
          )}
          <button
            onClick={() => nav('/rankings/' + (activeRunId ?? 'latest'))}
            style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}
          >
            <BarChart3 size={14} strokeWidth={2} />
            View rankings
          </button>
        </div>
      </motion.div>

      {/* ── Pipeline visualization ── */}
      <div className="card">
        <PipelineStages events={activeEvents} idle={!active} />
      </div>

      {/* ── Quick actions ── */}
      <div className="action-tiles stagger">
        <div className="action-tile" onClick={() => nav('/profile')}>
          <div className="icon"><Settings size={18} strokeWidth={2} /></div>
          <h3>Edit preferences</h3>
          <p>Thesis, sectors, stage, geography — drive every query.</p>
        </div>
        <div className="action-tile" onClick={() => nav('/filters')}>
          <div className="icon"><Sliders size={18} strokeWidth={2} /></div>
          <h3>Tune weights</h3>
          <p>Balance VC fit, novelty, and author credibility.</p>
        </div>
        <div className="action-tile" onClick={() => nav('/runs')}>
          <div className="icon"><History size={18} strokeWidth={2} /></div>
          <h3>Past runs</h3>
          <p>Revisit previous batches and export memo packs.</p>
        </div>
      </div>

      {/* ── Run config ── */}
      <div className="card">
        <h3>Run configuration</h3>
        <div className="grid-2">
          <div>
            <label>Mode</label>
            <select value={mode} onChange={(e) => setMode(e.target.value as any)}>
              <option value="single">Single round — one search + analysis pass</option>
              <option value="autonomous">Autonomous — keep discovering until time / paper cap</option>
            </select>

            <label>Queries per round</label>
            <input type="number" min={1} max={20} value={maxQueries} onChange={(e) => setMaxQueries(+e.target.value)} />

            <label>Papers per query</label>
            <input type="number" min={5} max={100} value={papersPerQuery} onChange={(e) => setPapersPerQuery(+e.target.value)} />

            <label>Deep analysis on top-K papers</label>
            <input type="number" min={1} max={20} value={topK} onChange={(e) => setTopK(+e.target.value)} />
          </div>

          <div>
            {mode === 'autonomous' ? (
              <>
                <label>Time limit (minutes)</label>
                <input type="number" min={5} max={600} value={timeLimit} onChange={(e) => setTimeLimit(+e.target.value)} />
                <label>Paper cap</label>
                <input type="number" min={20} max={2000} value={paperCap} onChange={(e) => setPaperCap(+e.target.value)} />
                <p className="sub" style={{ marginTop: 14 }}>
                  Run stops when either limit is hit. The Query Planner remembers angles already covered and proposes fresh ones each round.
                </p>
              </>
            ) : (
              <p className="sub" style={{ marginTop: 28 }}>
                Single-round mode: planner emits <strong>{maxQueries}</strong> queries, ingests up to{' '}
                <strong>{maxQueries * papersPerQuery}</strong> papers, triages everything, and runs
                deep bull/bear/judge on the top <strong>{topK}</strong>.
              </p>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
