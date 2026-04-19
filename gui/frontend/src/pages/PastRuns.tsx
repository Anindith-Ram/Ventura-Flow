import { motion } from 'framer-motion'
import { Download, ExternalLink } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api'
import type { RunRow } from '../types'

function formatDate(iso: string | null): string {
  if (!iso) return '—'
  const d = new Date(iso)
  return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' }) +
    ' · ' + d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })
}

function duration(start: string, end: string | null): string {
  if (!end) return 'running'
  const ms = new Date(end).getTime() - new Date(start).getTime()
  const m = Math.round(ms / 60000)
  if (m < 1) return '<1m'
  if (m < 60) return `${m}m`
  return `${Math.floor(m / 60)}h ${m % 60}m`
}

export function PastRuns() {
  const [runs, setRuns] = useState<RunRow[]>([])
  const [err, setErr] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    api.listRuns()
      .then((r) => { setRuns(r); setErr(null) })
      .catch((e) => setErr(e.message))
      .finally(() => setLoading(false))
  }, [])

  return (
    <div>
      <div className="header">
        <div>
          <h2>Past runs</h2>
          <div className="sub">
            {runs.length} run{runs.length === 1 ? '' : 's'} · click any row to revisit rankings and exports.
          </div>
        </div>
      </div>

      <div className="card">
        {loading && <p className="sub">Loading…</p>}
        {err && <p style={{ color: 'var(--berry)' }}>{err}</p>}
        {!loading && runs.length === 0 && !err && (
          <p className="sub">No runs yet. Kick one off from the home page.</p>
        )}
        {runs.length > 0 && (
          <table>
            <thead>
              <tr>
                <th>Run</th>
                <th>Mode</th>
                <th>Started</th>
                <th>Duration</th>
                <th style={{ textAlign: 'right' }}>Ingested</th>
                <th style={{ textAlign: 'right' }}>Triaged</th>
                <th style={{ textAlign: 'right' }}>Deep</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {runs.map((r, i) => (
                <motion.tr
                  key={r.run_id}
                  initial={{ opacity: 0, y: 4 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: Math.min(i, 10) * 0.025, duration: 0.25 }}
                >
                  <td>
                    <Link to={`/rankings/${r.run_id}`} style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
                      {r.run_id}
                      <ExternalLink size={11} strokeWidth={2} />
                    </Link>
                  </td>
                  <td>
                    <span className="badge">{r.mode}</span>
                  </td>
                  <td className="sub">{formatDate(r.started_at)}</td>
                  <td className="sub">{duration(r.started_at, r.finished_at)}</td>
                  <td style={{ textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}>{r.papers_ingested}</td>
                  <td style={{ textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}>{r.papers_passed_triage}</td>
                  <td style={{ textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}>{r.papers_deep_analyzed}</td>
                  <td style={{ textAlign: 'right' }}>
                    <a href={api.exportPdfUrl(r.run_id, 10)} style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
                      <Download size={12} strokeWidth={2} /> PDF
                    </a>
                  </td>
                </motion.tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}
