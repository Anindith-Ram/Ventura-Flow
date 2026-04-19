import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api'
import type { RunRow } from '../types'

export function PastRuns() {
  const [runs, setRuns] = useState<RunRow[]>([])
  const [err, setErr] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    api
      .listRuns()
      .then((r) => {
        setRuns(r)
        setErr(null)
      })
      .catch((e) => setErr(e.message))
      .finally(() => setLoading(false))
  }, [])

  return (
    <div>
      <div className="header">
        <h2>Past Runs</h2>
        <Link to="/">← Home</Link>
      </div>

      <div className="card">
        {loading && <p className="sub">Loading…</p>}
        {err && <p style={{ color: '#f87171' }}>{err}</p>}
        {!loading && runs.length === 0 && !err && (
          <p className="sub">No runs yet. Kick one off from the home page.</p>
        )}
        {runs.length > 0 && (
          <table>
            <thead>
              <tr>
                <th>Run ID</th>
                <th>Mode</th>
                <th>Started</th>
                <th>Finished</th>
                <th>Ingested</th>
                <th>Passed</th>
                <th>Deep</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {runs.map((r) => (
                <tr key={r.run_id}>
                  <td>
                    <Link to={`/rankings/${r.run_id}`}>{r.run_id}</Link>
                  </td>
                  <td>{r.mode}</td>
                  <td>{new Date(r.started_at).toLocaleString()}</td>
                  <td>{r.finished_at ? new Date(r.finished_at).toLocaleString() : <em>running</em>}</td>
                  <td>{r.papers_ingested}</td>
                  <td>{r.papers_passed_triage}</td>
                  <td>{r.papers_deep_analyzed}</td>
                  <td>
                    <a href={api.exportPdfUrl(r.run_id, 10)}>PDF</a>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}
