import { useStageStatus } from '../hooks/useStageStatus'
import type { PipelineEvent } from '../types'

interface Props {
  events: PipelineEvent[]
}

const FUNNEL_STAGES = ['ingest', 'dedup', 'triage', 'gate', 'deep_ingest', 'analysis']
const LABELS: Record<string, string> = {
  ingest: 'Ingested',
  dedup: 'Unique',
  triage: 'Scored',
  gate: 'Gated',
  deep_ingest: 'Full Text',
  analysis: 'Judged',
}

export function PipelineFunnel({ events }: Props) {
  const stages = useStageStatus(events)
  const relevant = stages.filter(s => FUNNEL_STAGES.includes(s.id))

  const counts = relevant.map(s => {
    const n = parseInt(s.count || '0', 10)
    return isNaN(n) ? 0 : n
  })

  const max = Math.max(...counts, 1)

  const anyData = counts.some(n => n > 0)
  if (!anyData) {
    return (
      <div className="funnel" style={{ justifyContent: 'center', alignItems: 'center', minHeight: 100 }}>
        <span style={{ color: 'var(--dim)', fontSize: 12 }}>Waiting for pipeline data…</span>
      </div>
    )
  }

  return (
    <div className="funnel">
      {relevant.map((stage, i) => {
        const n = counts[i]
        const pct = max > 0 ? (n / max) * 100 : 0
        const relativePct = counts[0] > 0 ? (n / counts[0]) * 100 : 0

        return (
          <div className="funnel-row" key={stage.id}>
            <span className="label">{LABELS[stage.id]}</span>
            <div className="bar">
              <div
                className="fill"
                style={{ width: `${pct}%` }}
              />
              {n > 0 && counts[0] > 0 && i > 0 && (
                <span className="pct">{relativePct.toFixed(0)}%</span>
              )}
            </div>
            <span className="count num">{n > 0 ? n : '—'}</span>
          </div>
        )
      })}
    </div>
  )
}
