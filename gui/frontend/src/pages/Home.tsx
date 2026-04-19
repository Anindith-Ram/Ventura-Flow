import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api'
import { Terminal } from '../components/Terminal'
import { useEventStream, useRunStatus } from '../store'

export function Home() {
  const nav = useNavigate()
  const { events, activeRunId } = useEventStream()
  const active = useRunStatus()

  const [mode, setMode] = useState<'single' | 'autonomous'>('single')
  const [timeLimit, setTimeLimit] = useState(60)
  const [paperCap, setPaperCap] = useState(200)
  const [maxQueries, setMaxQueries] = useState(6)
  const [papersPerQuery, setPapersPerQuery] = useState(20)
  const [topK, setTopK] = useState(5)
  const [starting, setStarting] = useState(false)

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

  return (
    <div>
      <div className="header">
        <div>
          <h2>Research Intelligence Pipeline</h2>
          <div className="sub">
            {active ? (
              <>
                <span className="badge active">● live</span> run {activeRunId}
              </>
            ) : (
              'idle — configure and start a run'
            )}
          </div>
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          <button onClick={() => nav('/profile')}>Edit VC Profile</button>
          <button onClick={() => nav('/runs')}>Past Runs</button>
        </div>
      </div>

      <div className="card">
        <h3>Start a new run</h3>
        <div className="grid-2">
          <div>
            <label>Mode</label>
            <select value={mode} onChange={(e) => setMode(e.target.value as any)}>
              <option value="single">Single round — one search + analysis pass</option>
              <option value="autonomous">
                Autonomous — keep discovering until time / paper cap
              </option>
            </select>

            <label>Queries per round</label>
            <input
              type="number" min={1} max={20}
              value={maxQueries} onChange={(e) => setMaxQueries(+e.target.value)}
            />

            <label>Papers per query</label>
            <input
              type="number" min={5} max={100}
              value={papersPerQuery} onChange={(e) => setPapersPerQuery(+e.target.value)}
            />

            <label>Deep analysis on top-K papers</label>
            <input
              type="number" min={1} max={20}
              value={topK} onChange={(e) => setTopK(+e.target.value)}
            />
          </div>

          <div>
            {mode === 'autonomous' && (
              <>
                <label>Time limit (minutes)</label>
                <input
                  type="number" min={5} max={600}
                  value={timeLimit} onChange={(e) => setTimeLimit(+e.target.value)}
                />
                <label>Paper cap</label>
                <input
                  type="number" min={20} max={2000}
                  value={paperCap} onChange={(e) => setPaperCap(+e.target.value)}
                />
                <p className="sub" style={{ marginTop: 12 }}>
                  Run stops when either limit is hit. The Query Planner tracks angles it
                  already covered and proposes fresh ones each round.
                </p>
              </>
            )}
            {mode === 'single' && (
              <p className="sub" style={{ marginTop: 32 }}>
                Single-round mode: planner emits {maxQueries} queries, ingests up to{' '}
                {maxQueries * papersPerQuery} papers, triages, then runs deep
                bull/bear/judge on the top {topK}.
              </p>
            )}
          </div>
        </div>

        <hr className="sep" />
        <div style={{ display: 'flex', gap: 8 }}>
          <button
            className="primary" disabled={active || starting} onClick={handleStart}
          >
            {starting ? 'Starting…' : active ? 'Run in progress' : 'Start run'}
          </button>
          {active && (
            <button className="danger" onClick={handleCancel}>
              Cancel
            </button>
          )}
          <button onClick={() => nav('/rankings/' + (activeRunId ?? 'latest'))} disabled={!activeRunId}>
            View live rankings →
          </button>
        </div>
      </div>

      <div className="card">
        <h3>Live pipeline output</h3>
        <Terminal events={events} />
      </div>
    </div>
  )
}
