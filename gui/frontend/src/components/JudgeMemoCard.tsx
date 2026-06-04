import { Cell, RadialBar, RadialBarChart, ResponsiveContainer } from 'recharts'

interface JudgeEval {
  verdict?: string
  investability?: number
  team_signal?: number
  commercial_viability?: number
  competitive_moat?: number
  rationale?: string
  recommendation?: string
  [key: string]: unknown
}

interface Props {
  judge: JudgeEval
}

const METRICS = [
  { key: 'investability',         label: 'Investability',   color: '#7c9cff' },
  { key: 'team_signal',           label: 'Team Signal',     color: '#4ade80' },
  { key: 'commercial_viability',  label: 'Commercial',      color: '#a78bfa' },
  { key: 'competitive_moat',      label: 'Moat',            color: '#fbbf24' },
] as const

function getVerdictClass(verdict?: string): string {
  if (!verdict) return ''
  const v = verdict.toLowerCase()
  if (v.includes('invest') || v.includes('strong') || v.includes('yes')) return 'invest'
  if (v.includes('pass') || v.includes('no') || v.includes('weak')) return 'pass'
  return 'watch'
}

function ScoreRing({ value, color, label }: { value: number; color: string; label: string }) {
  const pct = Math.min(100, Math.max(0, (value / 10) * 100))
  const data = [
    { value: pct, fill: color },
    { value: 100 - pct, fill: 'var(--surface-2)' },
  ]

  return (
    <div className="gauge">
      <div className="ring">
        <ResponsiveContainer width="100%" height="100%">
          <RadialBarChart
            cx="50%" cy="50%"
            innerRadius="65%" outerRadius="100%"
            startAngle={90} endAngle={-270}
            data={data}
            barSize={10}
          >
            <RadialBar dataKey="value" cornerRadius={4} background={false}>
              {data.map((_, i) => <Cell key={i} fill={data[i].fill} />)}
            </RadialBar>
          </RadialBarChart>
        </ResponsiveContainer>
      </div>
      <div className="value" style={{ color }}>{value?.toFixed(1) ?? '—'}</div>
      <div className="label">{label}</div>
    </div>
  )
}

export function JudgeMemoCard({ judge }: Props) {
  const verdictClass = getVerdictClass(judge.verdict || judge.recommendation as string)

  return (
    <div>
      {/* Verdict banner */}
      {(judge.verdict || judge.recommendation) && (
        <div style={{ marginBottom: 14, display: 'flex', alignItems: 'center', gap: 12 }}>
          <div className={`verdict ${verdictClass}`}>
            {verdictClass === 'invest' ? '✓' : verdictClass === 'pass' ? '✕' : '~'}
            {' '}
            {judge.verdict || judge.recommendation}
          </div>
        </div>
      )}

      {/* Score gauges */}
      <div className="gauge-grid" style={{ marginBottom: 16 }}>
        {METRICS.map(m => {
          const raw = judge[m.key]
          if (typeof raw !== 'number') return null
          return <ScoreRing key={m.key} value={raw} color={m.color} label={m.label} />
        })}
      </div>

      {/* Rationale */}
      {judge.rationale && (
        <div className="memo-section">
          <h4>Rationale</h4>
          <div className="body" style={{ whiteSpace: 'pre-wrap', lineHeight: 1.6 }}>
            {judge.rationale}
          </div>
        </div>
      )}

      {/* Other text fields */}
      {Object.entries(judge).map(([k, v]) => {
        if (['verdict', 'recommendation', 'rationale', ...METRICS.map(m => m.key)].includes(k)) return null
        if (typeof v !== 'string' && typeof v !== 'number') return null
        return (
          <div className="memo-section" key={k}>
            <h4>{k.replace(/_/g, ' ')}</h4>
            <div className="body">{String(v)}</div>
          </div>
        )
      })}
    </div>
  )
}
