import { useEffect, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import { Link, useParams } from 'react-router-dom'
import { api } from '../api'

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
  STRONG_FLAG: '#4ade80',
  FLAG: '#5fa8ff',
  WATCH_LIST: '#fbbf24',
  PASS: '#f87171',
}

const SEVERITY_COLORS: Record<string, string> = {
  HIGH: '#f87171',
  MEDIUM: '#fbbf24',
  LOW: '#4ade80',
}

function ScoreDimension({ label, score, rationale }: { label: string; score: number; rationale: string }) {
  const color = score >= 70 ? '#4ade80' : score >= 45 ? '#fbbf24' : '#f87171'
  return (
    <div style={{ marginBottom: 16 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
        <span style={{ fontSize: 12, color: '#8b93a4', textTransform: 'uppercase', letterSpacing: '0.05em' }}>{label}</span>
        <span style={{ fontWeight: 700, color, fontVariantNumeric: 'tabular-nums' }}>{score}/100</span>
      </div>
      <div style={{ background: '#1a1f2b', borderRadius: 4, height: 6, marginBottom: 6 }}>
        <div style={{ width: `${score}%`, background: color, height: '100%', borderRadius: 4, transition: 'width 0.4s' }} />
      </div>
      <p style={{ margin: 0, fontSize: 12, color: '#c9d1d9', lineHeight: 1.5 }}>{rationale}</p>
    </div>
  )
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div style={{ marginBottom: 20 }}>
      <div style={{ fontSize: 11, color: '#8b93a4', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 8 }}>{title}</div>
      {children}
    </div>
  )
}

export function PaperDetail() {
  const { runId, paperId } = useParams<{ runId: string; paperId: string }>()
  const [paper, setPaper] = useState<any | null>(null)
  const [artefacts, setArtefacts] = useState<Record<string, any>>({})
  const [err, setErr] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    if (!runId || !paperId) return
    api
      .getPaper(runId, paperId)
      .then((r) => { setPaper(r.paper); setArtefacts(r.artefacts); setErr(null) })
      .catch((e) => setErr(e.message))
      .finally(() => setLoading(false))
  }, [runId, paperId])

  if (loading) return <div>Loading…</div>
  if (err) return <div style={{ color: '#f87171' }}>{err}</div>
  if (!paper) return <div>Not found.</div>

  const judge: JudgeEval | null = artefacts['judge_evaluation.json'] ?? null
  const deck: PitchDeck | null = artefacts['pitch_deck.json'] ?? null
  const hasMemo = !!(judge && deck)

  return (
    <div>
      {/* ── Header ── */}
      <div className="header" style={{ alignItems: 'flex-start' }}>
        <div style={{ flex: 1, marginRight: 24 }}>
          <h2 style={{ marginBottom: 6 }}>{paper.title}</h2>
          <div className="sub">
            {(paper.authors || []).map((a: any) => a.name).join(', ') || 'Unknown authors'} ·{' '}
            {paper.year ?? '—'} · {paper.venue || paper.source || ''}
          </div>
          <div className="row" style={{ marginTop: 8 }}>
            {paper.url && <a href={paper.url} target="_blank" rel="noreferrer">OpenAlex ↗</a>}
            {paper.pdf_url && <a href={paper.pdf_url} target="_blank" rel="noreferrer">PDF ↗</a>}
          </div>
        </div>
        <Link to={`/rankings/${runId}`}>← Rankings</Link>
      </div>

      {/* ── Judge scorecard ── */}
      {judge ? (
        <>
          <div className="card">
            <div style={{ display: 'flex', alignItems: 'center', gap: 16, marginBottom: 20 }}>
              <div style={{
                fontSize: 48, fontWeight: 800, lineHeight: 1,
                color: REC_COLORS[judge.recommendation] ?? '#e6e9ef',
                fontVariantNumeric: 'tabular-nums',
              }}>
                {judge.investability_score}
              </div>
              <div>
                <div style={{
                  display: 'inline-block', padding: '4px 12px', borderRadius: 999,
                  background: REC_COLORS[judge.recommendation] + '22',
                  border: `1px solid ${REC_COLORS[judge.recommendation]}`,
                  color: REC_COLORS[judge.recommendation],
                  fontWeight: 700, fontSize: 13, marginBottom: 6,
                }}>
                  {judge.recommendation.replace('_', ' ')}
                </div>
                <div style={{ color: '#e6e9ef', fontSize: 15 }}>{judge.one_line_verdict}</div>
              </div>
            </div>
            <p style={{ color: '#8b93a4', fontSize: 13, margin: '0 0 20px' }}>{judge.investability_rationale}</p>

            <h3 style={{ marginBottom: 16 }}>Dimension scores</h3>
            <ScoreDimension label="Commercial viability" score={judge.commercial_viability} rationale={judge.commercial_viability_rationale} />
            <ScoreDimension label="Team signal" score={judge.team_signal_strength} rationale={judge.team_signal_rationale} />
            <ScoreDimension label="Timing & market" score={judge.timing_and_market} rationale={judge.timing_rationale} />
            <ScoreDimension label="Competitive moat" score={judge.competitive_moat} rationale={judge.moat_rationale} />
            <ScoreDimension label="Risk-adjusted conviction" score={judge.risk_adjusted_conviction} rationale={judge.risk_conviction_rationale} />
          </div>

          <div className="card">
            <h3>Bull vs Bear adjudication</h3>
            <div className="grid-2" style={{ gap: 20 }}>
              <div>
                <div style={{ fontSize: 12, color: '#4ade80', textTransform: 'uppercase', marginBottom: 8 }}>Bull prevailed on</div>
                {judge.bull_vs_bear_adjudication.bull_prevailed_on.length ? (
                  <ul style={{ margin: 0, paddingLeft: 18 }}>
                    {judge.bull_vs_bear_adjudication.bull_prevailed_on.map((p, i) => <li key={i} style={{ fontSize: 13, marginBottom: 6 }}>{p}</li>)}
                  </ul>
                ) : <span className="sub">—</span>}
              </div>
              <div>
                <div style={{ fontSize: 12, color: '#f87171', textTransform: 'uppercase', marginBottom: 8 }}>Bear prevailed on</div>
                {judge.bull_vs_bear_adjudication.bear_prevailed_on.length ? (
                  <ul style={{ margin: 0, paddingLeft: 18 }}>
                    {judge.bull_vs_bear_adjudication.bear_prevailed_on.map((p, i) => <li key={i} style={{ fontSize: 13, marginBottom: 6 }}>{p}</li>)}
                  </ul>
                ) : <span className="sub">—</span>}
              </div>
            </div>
            {judge.bull_vs_bear_adjudication.unresolved_tensions.length > 0 && (
              <div style={{ marginTop: 16 }}>
                <div style={{ fontSize: 12, color: '#fbbf24', textTransform: 'uppercase', marginBottom: 8 }}>Unresolved tensions</div>
                <ul style={{ margin: 0, paddingLeft: 18 }}>
                  {judge.bull_vs_bear_adjudication.unresolved_tensions.map((t, i) => <li key={i} style={{ fontSize: 13, marginBottom: 6 }}>{t}</li>)}
                </ul>
              </div>
            )}
            <div style={{ marginTop: 16, padding: '12px 14px', background: '#1a1f2b', borderRadius: 8, fontSize: 12, color: '#8b93a4' }}>
              <strong style={{ color: '#e6e9ef' }}>Evidence quality: </strong>{judge.evidence_quality_assessment}
            </div>
          </div>
        </>
      ) : (
        <div className="card">
          <p className="sub">Deep analysis (bull/bear/judge) was not run on this paper — it did not make the top-K cut for this run.</p>
        </div>
      )}

      {/* ── Pitch deck memo ── */}
      {deck && (
        <div className="card">
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 20 }}>
            <h3 style={{ margin: 0 }}>{deck.memo_title}</h3>
            <span className="sub">{deck.memo_date}</span>
          </div>

          <Section title="Executive summary">
            <p style={{ margin: 0, lineHeight: 1.7 }}>{deck.executive_summary}</p>
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
              <p style={{ margin: 0, fontSize: 13, lineHeight: 1.7, color: '#4ade80' }}>{deck.bull_case_narrative}</p>
            </Section>
            <Section title="Bear case">
              <p style={{ margin: 0, fontSize: 13, lineHeight: 1.7, color: '#f87171' }}>{deck.bear_case_narrative}</p>
            </Section>
          </div>

          <Section title="Key risks">
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {deck.key_risks_ranked.map((r, i) => (
                <div key={i} style={{ background: '#1a1f2b', borderRadius: 8, padding: '10px 14px' }}>
                  <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 4 }}>
                    <span style={{ fontSize: 11, fontWeight: 700, color: SEVERITY_COLORS[r.severity] ?? '#8b93a4' }}>{r.severity}</span>
                    <span style={{ fontSize: 13 }}>{r.risk}</span>
                  </div>
                  {r.mitigatable && r.mitigation_path && (
                    <div style={{ fontSize: 12, color: '#8b93a4' }}>Mitigation: {r.mitigation_path}</div>
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

          <div style={{
            padding: '12px 16px', borderRadius: 8, marginTop: 8,
            background: (REC_COLORS[deck.partner_meeting_recommendation?.split(' ')[0]] ?? '#5fa8ff') + '18',
            border: `1px solid ${REC_COLORS[deck.partner_meeting_recommendation?.split(' ')[0]] ?? '#5fa8ff'}44`,
          }}>
            <strong>Partner recommendation: </strong>{deck.partner_meeting_recommendation}
          </div>
        </div>
      )}

      {/* ── Researcher briefs / theses (collapsible prose) ── */}
      {(['bull_thesis.md', 'bear_critique.md', 'bull_brief.md', 'bear_brief.md'] as const).map((k) =>
        artefacts[k] ? (
          <details key={k} className="card" style={{ cursor: 'pointer' }}>
            <summary style={{ fontWeight: 600, fontSize: 14 }}>
              {k === 'bull_thesis.md' ? '🟢 Bull thesis' :
               k === 'bear_critique.md' ? '🔴 Bear critique' :
               k === 'bull_brief.md' ? 'Bull research brief' : 'Bear research brief'}
            </summary>
            <div style={{ marginTop: 12 }}>
              <ReactMarkdown>{String(artefacts[k])}</ReactMarkdown>
            </div>
          </details>
        ) : null,
      )}

      {/* ── Abstract ── */}
      <div className="card">
        <h3>Abstract</h3>
        <p style={{ margin: 0, lineHeight: 1.7 }}>{paper.abstract || <em className="sub">no abstract</em>}</p>
      </div>
    </div>
  )
}
