import { motion } from 'framer-motion'
import { useStageStatus } from '../hooks/useStageStatus'
import type { PipelineEvent } from '../types'

interface Props {
  events: PipelineEvent[]
  elapsed: number | null
}

export function StatGrid({ events, elapsed }: Props) {
  const stages = useStageStatus(events)

  const byId = Object.fromEntries(stages.map(s => [s.id, s]))

  const stats = [
    {
      label: 'Queries',
      value: byId.plan?.count || '—',
      sub: byId.plan?.status === 'done' ? 'planned' : byId.plan?.status === 'running' ? 'planning…' : 'pending',
    },
    {
      label: 'Papers Ingested',
      value: byId.ingest?.count || '—',
      sub: byId.ingest?.status === 'done' ? 'open-access' : byId.ingest?.status === 'running' ? 'fetching…' : 'pending',
    },
    {
      label: 'Top-K Gated',
      value: byId.gate?.count || '—',
      sub: byId.gate?.status === 'done' ? 'for deep analysis' : byId.gate?.status === 'running' ? 'selecting…' : 'pending',
    },
    {
      label: 'Memos',
      value: byId.analysis?.count || '—',
      sub: byId.analysis?.status === 'done' ? 'generated' : byId.analysis?.status === 'running' ? 'generating…' : 'pending',
    },
  ]

  return (
    <div className="grid-4" style={{ gap: 10 }}>
      {stats.map((s, i) => (
        <motion.div
          key={s.label}
          className="stat"
          initial={{ opacity: 0, scale: 0.97 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{ delay: i * 0.05, duration: 0.2 }}
        >
          <div className="label">{s.label}</div>
          <div className="value">{s.value}</div>
          <div className="delta">{s.sub}</div>
        </motion.div>
      ))}
    </div>
  )
}
