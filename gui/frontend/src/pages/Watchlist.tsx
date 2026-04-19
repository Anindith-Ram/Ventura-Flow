import { motion } from 'framer-motion'
import { Star, Trash2 } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api'
import type { WatchlistRow } from '../types'

function formatDate(iso: string): string {
  const d = new Date(iso)
  return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' })
}

export function Watchlist() {
  const [items, setItems] = useState<WatchlistRow[]>([])
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState<string | null>(null)

  async function refresh() {
    setLoading(true)
    try {
      const rows = await api.listWatchlist()
      setItems(rows); setErr(null)
    } catch (e: any) {
      setErr(e.message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { refresh() }, [])

  async function remove(paperId: string) {
    if (!confirm('Remove from watchlist?')) return
    await api.removeFromWatchlist(paperId)
    setItems((prev) => prev.filter((i) => i.paper_id !== paperId))
  }

  return (
    <div>
      <div className="header">
        <div>
          <h2 style={{ display: 'inline-flex', alignItems: 'center', gap: 10 }}>
            <Star size={20} strokeWidth={2.5} fill="var(--coral)" color="var(--coral)" />
            Watchlist
          </h2>
          <div className="sub">
            {items.length} paper{items.length === 1 ? '' : 's'} tracked across runs.
          </div>
        </div>
      </div>

      <div className="card">
        {loading && <p className="sub">Loading…</p>}
        {err && <p style={{ color: 'var(--berry)' }}>{err}</p>}
        {!loading && items.length === 0 && !err && (
          <p className="sub">
            Nothing starred yet. Click the star icon next to any paper to add it here.
          </p>
        )}
        {items.length > 0 && (
          <table>
            <thead>
              <tr>
                <th>Paper</th>
                <th>Added</th>
                <th>Source run</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {items.map((it, i) => (
                <motion.tr
                  key={it.paper_id}
                  initial={{ opacity: 0, y: 4 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: Math.min(i, 10) * 0.025, duration: 0.25 }}
                >
                  <td style={{ maxWidth: 500 }}>
                    {it.source_run ? (
                      <Link to={`/runs/${it.source_run}/paper/${encodeURIComponent(it.paper_id)}`}>
                        {it.title || it.paper_id}
                      </Link>
                    ) : (
                      <span>{it.title || it.paper_id}</span>
                    )}
                  </td>
                  <td className="sub">{formatDate(it.added_at)}</td>
                  <td className="sub" style={{ fontFamily: 'SF Mono, Menlo, monospace', fontSize: 12 }}>
                    {it.source_run ? (
                      <Link to={`/rankings/${it.source_run}`}>{it.source_run}</Link>
                    ) : '—'}
                  </td>
                  <td style={{ textAlign: 'right' }}>
                    <button
                      className="danger"
                      onClick={() => remove(it.paper_id)}
                      style={{ display: 'inline-flex', alignItems: 'center', gap: 4, padding: '4px 10px', fontSize: 12 }}
                    >
                      <Trash2 size={12} strokeWidth={2} />
                      Remove
                    </button>
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
