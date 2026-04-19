import { useEffect, useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api } from '../api'
import { Terminal } from '../components/Terminal'
import { useEventStream } from '../store'
import type { RunRow, TriageScore } from '../types'

type SortKey = 'composite' | 'vc_fit' | 'novelty' | 'credibility'

export function Rankings() {
  const { runId: paramId } = useParams<{ runId: string }>()
  const { events, activeRunId } = useEventStream()
  const runId = paramId && paramId !== 'latest' ? paramId : activeRunId

  const [run, setRun] = useState<RunRow | null>(null)
  const [scores, setScores] = useState<TriageScore[]>([])
  const [sortKey, setSortKey] = useState<SortKey>('composite')
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  useEffect(() => {
    if (!runId) return
    let cancelled = false
    const load = async () => {
      setLoading(true)
      try {
        const res = await api.getRun(runId)
        if (cancelled) return
        setRun(res.run)
        setScores(res.scores)
        setErr(null)
      } catch (e: any) {
        if (!cancelled) setErr(e.message)
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    load()
    const id = setInterval(load, 5000)
    return () => {
      cancelled = true
      clearInterval(id)
    }
  }, [runId])

  const sorted = useMemo(
    () => [...scores].sort((a, b) => b[sortKey] - a[sortKey]),
    [scores, sortKey],
  )

  const subfieldCounts = useMemo(() => {
    const m = new Map<string, number>()
    for (const s of scores) m.set(s.subfield || 'unknown', (m.get(s.subfield || 'unknown') ?? 0) + 1)
    return [...m.entries()].sort((a, b) => b[1] - a[1])
  }, [scores])

  if (!runId) {
    return (
      <div>
        <h2>Rankings</h2>
        <p className="sub">No active run. Start one from the home page to see live rankings.</p>
        <Link to="/">← Home</Link>
      </div>
    )
  }

  return (
    <div>
      <div className="header">
        <div>
          <h2>Rankings — {runId}</h2>
          <div className="sub">
            {run ? (
              <>
                {run.mode} · ingested {run.papers_ingested} · triaged{' '}
                {run.papers_passed_triage} · deep {run.papers_deep_analyzed}
              </>
            ) : loading ? (
              'loading…'
            ) : err ? (
              <span style={{ color: '#f87171' }}>{err}</span>
            ) : (
              'waiting for first results'
            )}
          </div>
        </div>
        {run && (
          <a className="primary" href={api.exportPdfUrl(runId, 10)}>
            Export memo pack (PDF)
          </a>
        )}
      </div>

      {subfieldCounts.length > 0 && (
        <div className="card">
          <h3>Subfield mix</h3>
          <div className="row">
            {subfieldCounts.map(([k, n]) => (
              <span key={k} className="chip">
                {k} · {n}
              </span>
            ))}
          </div>
        </div>
      )}

      <div className="card">
        <h3>Papers</h3>
        <p className="sub">Hover a rationale for the full agent reasoning. Click a row to drill in.</p>
        <table>
          <thead>
            <tr>
              <th>#</th>
              <th>Paper</th>
              <th>Subfield</th>
              {(['composite', 'vc_fit', 'novelty', 'credibility'] as SortKey[]).map((k) => (
                <th
                  key={k}
                  className={sortKey === k ? 'active' : ''}
                  onClick={() => setSortKey(k)}
                  style={{ cursor: 'pointer' }}
                >
                  {k} {sortKey === k ? '↓' : ''}
                </th>
              ))}
              <th>Rationale</th>
            </tr>
          </thead>
          <tbody>
            {sorted.map((s, i) => (
              <tr key={s.paper_id}>
                <td>{i + 1}</td>
                <td style={{ maxWidth: 340 }}>
                  <Link to={`/runs/${runId}/paper/${encodeURIComponent(s.paper_id)}`}>
                    {s.title || s.paper_id}
                  </Link>
                  {s.has_memo && (
                    <span className="badge active" style={{ marginLeft: 6 }}>memo</span>
                  )}
                </td>
                <td>{s.subfield || '—'}</td>
                <td><strong>{s.composite.toFixed(1)}</strong></td>
                <td>{s.vc_fit.toFixed(1)}</td>
                <td>{s.novelty.toFixed(1)}</td>
                <td>{s.credibility.toFixed(1)}</td>
                <td className="rationale" title={s.rationale}>
                  {s.rationale.length > 120 ? s.rationale.slice(0, 120) + '…' : s.rationale}
                </td>
              </tr>
            ))}
            {sorted.length === 0 && (
              <tr>
                <td colSpan={8} className="sub" style={{ textAlign: 'center', padding: 20 }}>
                  No triage scores yet.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      <div className="card">
        <h3>Live pipeline output</h3>
        <Terminal events={events.filter((e) => !runId || e.run_id === runId)} />
      </div>
    </div>
  )
}
