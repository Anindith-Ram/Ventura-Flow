import { useEffect, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import { Link, useParams } from 'react-router-dom'
import { api } from '../api'

type Artefacts = Record<string, any>

export function PaperDetail() {
  const { runId, paperId } = useParams<{ runId: string; paperId: string }>()
  const [paper, setPaper] = useState<any | null>(null)
  const [artefacts, setArtefacts] = useState<Artefacts>({})
  const [err, setErr] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    if (!runId || !paperId) return
    api
      .getPaper(runId, paperId)
      .then((r) => {
        setPaper(r.paper)
        setArtefacts(r.artefacts)
        setErr(null)
      })
      .catch((e) => setErr(e.message))
      .finally(() => setLoading(false))
  }, [runId, paperId])

  if (loading) return <div>Loading paper…</div>
  if (err) return <div style={{ color: '#f87171' }}>{err}</div>
  if (!paper) return <div>Not found.</div>

  const judge = artefacts['judge_evaluation.json']
  const deck = artefacts['pitch_deck.json']

  return (
    <div>
      <div className="header">
        <div>
          <h2 style={{ marginBottom: 4 }}>{paper.title}</h2>
          <div className="sub">
            {(paper.authors || []).map((a: any) => a.name).join(', ') || 'Unknown authors'} ·{' '}
            {paper.year ?? '—'} · {paper.venue || paper.source || ''}
          </div>
        </div>
        <Link to={`/rankings/${runId}`}>← Rankings</Link>
      </div>

      <div className="card">
        <h3>Abstract</h3>
        <p>{paper.abstract || <em className="sub">no abstract</em>}</p>
        <div className="row" style={{ marginTop: 10 }}>
          {paper.url && (
            <a href={paper.url} target="_blank" rel="noreferrer">
              OpenAlex entry ↗
            </a>
          )}
          {paper.pdf_url && (
            <a href={paper.pdf_url} target="_blank" rel="noreferrer">
              PDF ↗
            </a>
          )}
        </div>
      </div>

      {judge && (
        <div className="card">
          <h3>Judge evaluation</h3>
          <pre style={{ whiteSpace: 'pre-wrap' }}>{JSON.stringify(judge, null, 2)}</pre>
        </div>
      )}

      {deck && (
        <div className="card">
          <h3>Pitch deck</h3>
          <pre style={{ whiteSpace: 'pre-wrap' }}>{JSON.stringify(deck, null, 2)}</pre>
        </div>
      )}

      {(['bull_thesis.md', 'bear_critique.md', 'bull_brief.md', 'bear_brief.md'] as const).map((k) =>
        artefacts[k] ? (
          <div className="card" key={k}>
            <h3>{k.replace('.md', '').replace('_', ' ')}</h3>
            <ReactMarkdown>{String(artefacts[k])}</ReactMarkdown>
          </div>
        ) : null,
      )}
    </div>
  )
}
