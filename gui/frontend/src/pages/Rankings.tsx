import { motion } from 'framer-motion'
import { ArrowDown, ChevronLeft, Download } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api } from '../api'
import { CountUp } from '../components/CountUp'
import { PipelineStages } from '../components/PipelineStages'
import { StarButton } from '../components/StarButton'
import { useEventStream } from '../store'
import type { RunRow, TriageScore } from '../types'

type SortKey = 'composite' | 'vc_fit' | 'novelty' | 'credibility'

function scoreClass(v: number): 'high' | 'mid' | 'low' {
  if (v >= 70) return 'high'
  if (v >= 45) return 'mid'
  return 'low'
}

export function Rankings() {
  const { runId: paramId } = useParams<{ runId: string }>()
  const { events, activeRunId } = useEventStream()
  const [fallbackRunId, setFallbackRunId] = useState<string | null>(null)

  useEffect(() => {
    if (paramId !== 'latest' || activeRunId) return
    api.listRuns().then((runs) => {
      if (runs.length > 0) setFallbackRunId(runs[0].run_id)
    })
  }, [paramId, activeRunId])

  const runId =
    paramId && paramId !== 'latest' ? paramId : activeRunId ?? fallbackRunId

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
        setRun(res.run); setScores(res.scores); setErr(null)
      } catch (e: any) {
        if (!cancelled) setErr(e.message)
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    load()
    const id = setInterval(load, 5000)
    return () => { cancelled = true; clearInterval(id) }
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
        <p className="sub">No runs yet. Start one from the home page.</p>
        <Link to="/"><ChevronLeft size={14} style={{ verticalAlign: 'middle' }} /> Home</Link>
      </div>
    )
  }

  const runEvents = events.filter((e) => e.run_id === runId)
  const isLive = runId === activeRunId

  return (
    <div>
      <div className="header">
        <div>
          <h2>
            Rankings
            {isLive && <span className="badge coral" style={{ marginLeft: 10, fontSize: 11 }}>● LIVE</span>}
          </h2>
          <div className="sub" style={{ fontFamily: 'SF Mono, Menlo, monospace', fontSize: 12 }}>
            {runId}
            {run && (
              <> · {run.mode} · {run.papers_ingested} ingested · {run.papers_passed_triage} triaged · {run.papers_deep_analyzed} deep</>
            )}
            {!run && loading && ' · loading…'}
            {err && <span style={{ color: 'var(--berry)' }}> · {err}</span>}
          </div>
        </div>
        {run && (
          <a className="primary" href={api.exportPdfUrl(runId, 10)} style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
            <Download size={14} strokeWidth={2.5} />
            Memo pack (PDF)
          </a>
        )}
      </div>

      {isLive && (
        <div className="card">
          <PipelineStages events={runEvents} idle={false} />
        </div>
      )}

      {subfieldCounts.length > 0 && (
        <div className="card">
          <h3>Subfield mix</h3>
          <div className="row">
            {subfieldCounts.map(([k, n]) => (
              <span key={k} className="chip">{k} · {n}</span>
            ))}
          </div>
        </div>
      )}

      <div className="card">
        <h3>Papers</h3>
        <p className="sub" style={{ marginBottom: 12 }}>
          Hover a rationale for the full agent reasoning. Click a row for deep-analysis memo.
        </p>
        <table>
          <thead>
            <tr>
              <th style={{ width: 32 }}>#</th>
              <th style={{ width: 32 }}></th>
              <th>Paper</th>
              <th>Subfield</th>
              {(['composite', 'vc_fit', 'novelty', 'credibility'] as SortKey[]).map((k) => (
                <th
                  key={k}
                  className={sortKey === k ? 'active' : ''}
                  onClick={() => setSortKey(k)}
                  style={{ cursor: 'pointer', userSelect: 'none' }}
                >
                  <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
                    {k.replace('_', ' ')}
                    {sortKey === k && <ArrowDown size={11} strokeWidth={2.5} />}
                  </span>
                </th>
              ))}
              <th>Rationale</th>
            </tr>
          </thead>
          <tbody>
            {sorted.map((s, i) => {
              const c = scoreClass(s.composite)
              return (
                <motion.tr
                  key={s.paper_id}
                  initial={{ opacity: 0, y: 4 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: Math.min(i, 10) * 0.025, duration: 0.25 }}
                >
                  <td style={{ color: 'var(--muted)', fontWeight: 600, fontVariantNumeric: 'tabular-nums' }}>
                    {i + 1}
                  </td>
                  <td>
                    <StarButton paperId={s.paper_id} runId={runId} initial={false} size={14} />
                  </td>
                  <td style={{ maxWidth: 380 }}>
                    <Link to={`/runs/${runId}/paper/${encodeURIComponent(s.paper_id)}`}>
                      {s.title || s.paper_id}
                    </Link>
                    {s.has_memo && (
                      <span className="badge active" style={{ marginLeft: 8 }}>memo</span>
                    )}
                  </td>
                  <td className="sub">{s.subfield || '—'}</td>
                  <td>
                    <span className={`score-pill ${c}`}>
                      <CountUp to={s.composite} duration={900} />
                    </span>
                  </td>
                  <td>{s.vc_fit.toFixed(0)}</td>
                  <td>{s.novelty.toFixed(0)}</td>
                  <td>{s.credibility.toFixed(0)}</td>
                  <td className="rationale" title={s.rationale}>
                    {s.rationale.length > 110 ? s.rationale.slice(0, 110) + '…' : s.rationale}
                  </td>
                </motion.tr>
              )
            })}
            {sorted.length === 0 && (
              <tr>
                <td colSpan={9} className="sub" style={{ textAlign: 'center', padding: 32 }}>
                  No triage scores yet.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}
