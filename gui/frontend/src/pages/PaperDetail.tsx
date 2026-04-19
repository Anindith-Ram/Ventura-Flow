import { motion } from 'framer-motion'
import { ChevronLeft, ExternalLink, FileText, RefreshCw } from 'lucide-react'
import { marked } from 'marked'
import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api } from '../api'
import { AuthorHoverCard } from '../components/AuthorHoverCard'
import { CountUp } from '../components/CountUp'
import { StarButton } from '../components/StarButton'

function Prose({ children }: { children: string }) {
  return (
    <div
      className="prose"
      dangerouslySetInnerHTML={{ __html: marked(children) as string }}
    />
  )
}

type JudgeEval = {
  investability_score: number
  investability_rationale: string
  commercial_viability: number
  commercial_viability_rationale: string
  team_signal_strength: number
  team_signal_rationale: string
  timing_and_market: number
  timing_rationale: string
  competitive_moat: number
  moat_rationale: string
  risk_adjusted_conviction: number
  risk_conviction_rationale: string
  recommendation: 'STRONG_FLAG' | 'FLAG' | 'WATCH_LIST' | 'PASS'
  one_line_verdict: string
  evidence_quality_assessment: string
  bull_vs_bear_adjudication: {
    bull_prevailed_on: string[]
    bear_prevailed_on: string[]
    unresolved_tensions: string[]
  }
}

type PitchDeck = {
  memo_title: string
  memo_date: string
  executive_summary: string
  the_opportunity: string
  technology_differentiation: string
  team_assessment: string
  market_landscape: string
  bull_case_narrative: string
  bear_case_narrative: string
  key_risks_ranked: { risk: string; severity: string; mitigatable: boolean; mitigation_path?: string }[]
  what_we_need_to_believe: string[]
  suggested_next_steps: string[]
  comparable_transactions: string
  partner_meeting_recommendation: string
}

const REC_COLORS: Record<string, string> = {
  STRONG_FLAG: 'var(--seaweed)',
  FLAG: 'var(--coral)',
  WATCH_LIST: 'var(--sun)',
  PASS: 'var(--berry)',
}
const REC_BG: Record<string, string> = {
  STRONG_FLAG: 'var(--artichoke-bg)',
  FLAG: 'var(--coral-bg)',
  WATCH_LIST: '#fbf1d9',
  PASS: '#f5dce1',
}
const SEVERITY_COLORS: Record<string, string> = {
  HIGH: 'var(--berry)',
  MEDIUM: 'var(--coral-dark)',
  LOW: 'var(--seaweed)',
}

function scoreClass(v: number): 'high' | 'mid' | 'low' {
  if (v >= 70) return 'high'
  if (v >= 45) return 'mid'
  return 'low'
}

function ScoreDimension({ label, score, rationale }: { label: string; score: number; rationale: string }) {
  const cls = scoreClass(score)
  return (
    <div style={{ marginBottom: 18 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 6 }}>
        <span style={{ fontSize: 11, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: '0.06em', fontWeight: 600 }}>
          {label}
        </span>
        <span className={`score-pill ${cls}`}>{score}/100</span>
      </div>
      <div className="bar" style={{ marginBottom: 8 }}>
        <motion.div
          className={`bar-fill ${cls}`}
          initial={{ width: 0 }}
          animate={{ width: `${score}%` }}
          transition={{ duration: 0.8, ease: [0.22, 1, 0.36, 1] }}
        />
      </div>
      <p style={{ margin: 0, fontSize: 12.5, color: 'var(--text-soft)', lineHeight: 1.55 }}>{rationale}</p>
    </div>
  )
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="memo-section">
      <h4>{title}</h4>
      {children}
    </div>
  )
}

export function PaperDetail() {
  const { runId, paperId } = useParams<{ runId: string; paperId: string }>()
  const [paper, setPaper] = useState<any | null>(null)
  const [artefacts, setArtefacts] = useState<Record<string, any>>({})
  const [watchlisted, setWatchlisted] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [reanalyzing, setReanalyzing] = useState(false)

  useEffect(() => {
    if (!runId || !paperId) return
    let cancelled = false
    const load = () => api
      .getPaper(runId, paperId)
      .then((r) => {
        if (cancelled) return
        setPaper(r.paper); setArtefacts(r.artefacts); setWatchlisted(r.watchlisted); setErr(null)
      })
      .catch((e) => !cancelled && setErr(e.message))
      .finally(() => !cancelled && setLoading(false))
    load()
    return () => { cancelled = true }
  }, [runId, paperId])

  async function handleReanalyze() {
    if (!runId || !paperId) return
    if (!confirm('Re-run bull/bear/judge on this paper? Takes 1–3 minutes.')) return
    setReanalyzing(true)
    try {
      await api.reanalyzePaper(runId, paperId)
      alert('Re-analysis started. Refresh in a minute or two to see updated results.')
    } catch (e: any) {
      alert(`Failed: ${e.message}`)
    } finally {
      setReanalyzing(false)
    }
  }

  if (loading) return <div className="sub">Loading…</div>
  if (err) return <div style={{ color: 'var(--berry)' }}>{err}</div>
  if (!paper) return <div>Not found.</div>

  const judge: JudgeEval | null = artefacts['judge_evaluation.json'] ?? null
  const deck: PitchDeck | null = artefacts['pitch_deck.json'] ?? null

  return (
    <div>
      <div className="header" style={{ alignItems: 'flex-start' }}>
        <div style={{ flex: 1, marginRight: 24 }}>
          <Link to={`/rankings/${runId}`} style={{ display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 13, marginBottom: 8 }}>
            <ChevronLeft size={14} strokeWidth={2.5} /> Rankings
          </Link>
          <div style={{ display: 'flex', alignItems: 'flex-start', gap: 10 }}>
            <h2 style={{ marginBottom: 6, flex: 1 }}>{paper.title}</h2>
            <StarButton paperId={paperId!} runId={runId} initial={watchlisted} size={20} onChange={setWatchlisted} />
          </div>
          <div className="sub" style={{ display: 'flex', flexWrap: 'wrap', gap: 4, alignItems: 'baseline' }}>
            {(paper.authors || []).length === 0
              ? <span>Unknown authors</span>
              : (paper.authors || []).map((a: any, i: number) => (
                  <span key={i}>
                    <AuthorHoverCard author={a} />
                    {i < paper.authors.length - 1 && <span style={{ marginRight: 2 }}>,</span>}
                  </span>
                ))
            }
            <span style={{ margin: '0 4px' }}>·</span>
            <span>{paper.year ?? '—'}</span>
            <span style={{ margin: '0 4px' }}>·</span>
            <span>{paper.venue || paper.source || ''}</span>
          </div>
          <div className="row" style={{ marginTop: 12 }}>
            {paper.url && (
              <a href={paper.url} target="_blank" rel="noreferrer" style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
                <ExternalLink size={12} strokeWidth={2} /> OpenAlex
              </a>
            )}
            {paper.pdf_url && (
              <a href={paper.pdf_url} target="_blank" rel="noreferrer" style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
                <FileText size={12} strokeWidth={2} /> PDF
              </a>
            )}
            <button
              onClick={handleReanalyze}
              disabled={reanalyzing}
              style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 12, padding: '6px 12px' }}
            >
              <RefreshCw size={12} strokeWidth={2} className={reanalyzing ? 'spin' : ''} />
              {reanalyzing ? 'Starting…' : 'Re-analyze'}
            </button>
          </div>
        </div>
      </div>

      {judge ? (
        <>
          <motion.div
            className="card"
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.35 }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: 20, marginBottom: 22 }}>
              <motion.div
                initial={{ scale: 0.7, opacity: 0 }}
                animate={{ scale: 1, opacity: 1 }}
                transition={{ delay: 0.1, duration: 0.4, ease: [0.22, 1, 0.36, 1] }}
                style={{
                  fontSize: 56, fontWeight: 800, lineHeight: 1,
                  color: REC_COLORS[judge.recommendation] ?? 'var(--text)',
                  fontVariantNumeric: 'tabular-nums',
                  letterSpacing: '-0.03em',
                }}
              >
                <CountUp to={judge.investability_score} duration={1400} />
              </motion.div>
              <div>
                <div style={{
                  display: 'inline-block', padding: '5px 14px', borderRadius: 999,
                  background: REC_BG[judge.recommendation],
                  border: `1px solid ${REC_COLORS[judge.recommendation]}`,
                  color: REC_COLORS[judge.recommendation],
                  fontWeight: 700, fontSize: 12, marginBottom: 8,
                  letterSpacing: '0.04em',
                }}>
                  {judge.recommendation.replace('_', ' ')}
                </div>
                <div style={{ color: 'var(--text)', fontSize: 16, fontWeight: 600, letterSpacing: '-0.005em' }}>
                  {judge.one_line_verdict}
                </div>
              </div>
            </div>
            <p style={{ color: 'var(--muted)', fontSize: 13.5, margin: '0 0 24px', lineHeight: 1.6 }}>
              {judge.investability_rationale}
            </p>

            <h3 style={{ marginBottom: 16 }}>Dimension scores</h3>
            <ScoreDimension label="Commercial viability" score={judge.commercial_viability} rationale={judge.commercial_viability_rationale} />
            <ScoreDimension label="Team signal" score={judge.team_signal_strength} rationale={judge.team_signal_rationale} />
            <ScoreDimension label="Timing & market" score={judge.timing_and_market} rationale={judge.timing_rationale} />
            <ScoreDimension label="Competitive moat" score={judge.competitive_moat} rationale={judge.moat_rationale} />
            <ScoreDimension label="Risk-adjusted conviction" score={judge.risk_adjusted_conviction} rationale={judge.risk_conviction_rationale} />
          </motion.div>

          <div className="card">
            <h3>Bull vs Bear adjudication</h3>
            <div className="grid-2" style={{ gap: 20 }}>
              <div>
                <div style={{ fontSize: 11, color: 'var(--seaweed)', textTransform: 'uppercase', letterSpacing: '0.08em', fontWeight: 700, marginBottom: 10 }}>
                  Bull prevailed on
                </div>
                {judge.bull_vs_bear_adjudication.bull_prevailed_on.length ? (
                  <ul style={{ margin: 0, paddingLeft: 18 }}>
                    {judge.bull_vs_bear_adjudication.bull_prevailed_on.map((p, i) =>
                      <li key={i} style={{ fontSize: 13, marginBottom: 6 }}>{p}</li>)}
                  </ul>
                ) : <span className="sub">—</span>}
              </div>
              <div>
                <div style={{ fontSize: 11, color: 'var(--berry)', textTransform: 'uppercase', letterSpacing: '0.08em', fontWeight: 700, marginBottom: 10 }}>
                  Bear prevailed on
                </div>
                {judge.bull_vs_bear_adjudication.bear_prevailed_on.length ? (
                  <ul style={{ margin: 0, paddingLeft: 18 }}>
                    {judge.bull_vs_bear_adjudication.bear_prevailed_on.map((p, i) =>
                      <li key={i} style={{ fontSize: 13, marginBottom: 6 }}>{p}</li>)}
                  </ul>
                ) : <span className="sub">—</span>}
              </div>
            </div>
            {judge.bull_vs_bear_adjudication.unresolved_tensions.length > 0 && (
              <div style={{ marginTop: 18 }}>
                <div style={{ fontSize: 11, color: 'var(--coral-dark)', textTransform: 'uppercase', letterSpacing: '0.08em', fontWeight: 700, marginBottom: 10 }}>
                  Unresolved tensions
                </div>
                <ul style={{ margin: 0, paddingLeft: 18 }}>
                  {judge.bull_vs_bear_adjudication.unresolved_tensions.map((t, i) =>
                    <li key={i} style={{ fontSize: 13, marginBottom: 6 }}>{t}</li>)}
                </ul>
              </div>
            )}
            <div style={{ marginTop: 18, padding: '12px 14px', background: 'var(--panel-2)', border: '1px solid var(--line)', borderRadius: 8, fontSize: 12.5, color: 'var(--muted)' }}>
              <strong style={{ color: 'var(--text)' }}>Evidence quality: </strong>{judge.evidence_quality_assessment}
            </div>
          </div>
        </>
      ) : (
        <div className="card">
          <p className="sub">Deep analysis (bull/bear/judge) was not run on this paper — it did not make the top-K cut for this run.</p>
        </div>
      )}

      {deck && (
        <div className="card">
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 20 }}>
            <h3 style={{ margin: 0, fontSize: 17 }}>{deck.memo_title}</h3>
            <span className="sub">{deck.memo_date}</span>
          </div>

          <Section title="Executive summary">
            <p style={{ margin: 0, lineHeight: 1.7, fontSize: 14 }}>{deck.executive_summary}</p>
          </Section>

          <div className="grid-2">
            <Section title="The opportunity">
              <p style={{ margin: 0, fontSize: 13, lineHeight: 1.7 }}>{deck.the_opportunity}</p>
            </Section>
            <Section title="Technology differentiation">
              <p style={{ margin: 0, fontSize: 13, lineHeight: 1.7 }}>{deck.technology_differentiation}</p>
            </Section>
            <Section title="Team">
              <p style={{ margin: 0, fontSize: 13, lineHeight: 1.7 }}>{deck.team_assessment}</p>
            </Section>
            <Section title="Market landscape">
              <p style={{ margin: 0, fontSize: 13, lineHeight: 1.7 }}>{deck.market_landscape}</p>
            </Section>
          </div>

          <div className="grid-2" style={{ marginTop: 4 }}>
            <Section title="Bull case">
              <p style={{ margin: 0, fontSize: 13, lineHeight: 1.7, color: 'var(--seaweed)' }}>{deck.bull_case_narrative}</p>
            </Section>
            <Section title="Bear case">
              <p style={{ margin: 0, fontSize: 13, lineHeight: 1.7, color: 'var(--berry)' }}>{deck.bear_case_narrative}</p>
            </Section>
          </div>

          <Section title="Key risks">
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {deck.key_risks_ranked.map((r, i) => (
                <div key={i} style={{ background: 'var(--panel-2)', border: '1px solid var(--line)', borderRadius: 8, padding: '12px 14px' }}>
                  <div style={{ display: 'flex', gap: 10, alignItems: 'center', marginBottom: 4 }}>
                    <span style={{ fontSize: 10.5, fontWeight: 800, color: SEVERITY_COLORS[r.severity] ?? 'var(--muted)', letterSpacing: '0.06em' }}>
                      {r.severity}
                    </span>
                    <span style={{ fontSize: 13 }}>{r.risk}</span>
                  </div>
                  {r.mitigatable && r.mitigation_path && (
                    <div style={{ fontSize: 12, color: 'var(--muted)' }}>Mitigation: {r.mitigation_path}</div>
                  )}
                </div>
              ))}
            </div>
          </Section>

          <div className="grid-2">
            <Section title="What we need to believe">
              <ul style={{ margin: 0, paddingLeft: 18 }}>
                {deck.what_we_need_to_believe.map((b, i) => <li key={i} style={{ fontSize: 13, marginBottom: 6 }}>{b}</li>)}
              </ul>
            </Section>
            <Section title="Suggested next steps">
              <ul style={{ margin: 0, paddingLeft: 18 }}>
                {deck.suggested_next_steps.map((s, i) => <li key={i} style={{ fontSize: 13, marginBottom: 6 }}>{s}</li>)}
              </ul>
            </Section>
          </div>

          <Section title="Comparable transactions">
            <p style={{ margin: 0, fontSize: 13, lineHeight: 1.7 }}>{deck.comparable_transactions}</p>
          </Section>

          {(() => {
            const rec = deck.partner_meeting_recommendation?.split(' ')[0] ?? 'FLAG'
            const fg = REC_COLORS[rec] ?? 'var(--coral)'
            const bg = REC_BG[rec] ?? 'var(--coral-bg)'
            return (
              <div style={{
                padding: '14px 18px', borderRadius: 10, marginTop: 10,
                background: bg, border: `1px solid ${fg}`,
              }}>
                <strong style={{ color: fg }}>Partner recommendation: </strong>
                <span style={{ color: 'var(--text)' }}>{deck.partner_meeting_recommendation}</span>
              </div>
            )
          })()}
        </div>
      )}

      {(['bull_thesis.md', 'bear_critique.md', 'bull_brief.md', 'bear_brief.md'] as const).map((k) =>
        artefacts[k] ? (
          <details key={k} className="card" style={{ cursor: 'pointer' }}>
            <summary style={{ fontWeight: 700, fontSize: 14 }}>
              {k === 'bull_thesis.md' ? 'Bull thesis' :
               k === 'bear_critique.md' ? 'Bear critique' :
               k === 'bull_brief.md' ? 'Bull research brief' : 'Bear research brief'}
            </summary>
            <div style={{ marginTop: 14 }}>
              <Prose>{String(artefacts[k])}</Prose>
            </div>
          </details>
        ) : null,
      )}

      <div className="card">
        <h3>Abstract</h3>
        <p style={{ margin: 0, lineHeight: 1.7 }}>
          {paper.abstract || <em className="sub">no abstract</em>}
        </p>
      </div>
    </div>
  )
}
