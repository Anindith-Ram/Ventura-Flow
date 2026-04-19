import { motion } from 'framer-motion'
import {
  Brain, Download, Filter, Gavel, Layers, Scale, Search,
  type LucideIcon,
} from 'lucide-react'
import type { PipelineEvent } from '../types'

type StageStatus = 'pending' | 'active' | 'complete'

interface StageDef {
  key: string
  label: string
  detail: string
  icon: LucideIcon
}

const STAGES: StageDef[] = [
  { key: 'plan', label: 'Query Planner', detail: 'Generating research angles from your thesis', icon: Brain },
  { key: 'ingest', label: 'OpenAlex Ingest', detail: 'Searching academic corpus', icon: Search },
  { key: 'dedup', label: 'Deduplicate', detail: 'Removing near-duplicate papers', icon: Filter },
  { key: 'triage', label: 'Agentic Triage', detail: 'Scoring relevance · novelty · credibility', icon: Scale },
  { key: 'gate', label: 'Diversity Gate', detail: 'Selecting top-K across subfields', icon: Layers },
  { key: 'deep_ingest', label: 'PDF Extract', detail: 'Downloading full text', icon: Download },
  { key: 'analysis', label: 'Bull vs Bear vs Judge', detail: 'Deep adversarial analysis', icon: Gavel },
]

function statusesFromEvents(events: PipelineEvent[]): Record<string, StageStatus> {
  const statuses: Record<string, StageStatus> = Object.fromEntries(
    STAGES.map((s) => [s.key, 'pending']),
  )
  for (const ev of events) {
    if (!(ev.stage in statuses)) continue
    if (ev.level === 'stage_start') statuses[ev.stage] = 'active'
    else if (ev.level === 'stage_end') statuses[ev.stage] = 'complete'
  }
  // If a later stage is active/complete, earlier stages must be complete.
  let seenActiveOrComplete = false
  for (let i = STAGES.length - 1; i >= 0; i--) {
    const k = STAGES[i].key
    if (statuses[k] === 'active' || statuses[k] === 'complete') {
      seenActiveOrComplete = true
    } else if (seenActiveOrComplete) {
      statuses[k] = 'complete'
    }
  }
  return statuses
}

function latestDetail(events: PipelineEvent[], stage: string): string | null {
  for (let i = events.length - 1; i >= 0; i--) {
    if (events[i].stage === stage && events[i].level !== 'stage_start' && events[i].level !== 'stage_end') {
      return events[i].message
    }
  }
  return null
}

export function PipelineStages({ events, idle }: { events: PipelineEvent[]; idle: boolean }) {
  const statuses = statusesFromEvents(events)
  const completeCount = STAGES.filter((s) => statuses[s.key] === 'complete').length
  const activeCount = STAGES.filter((s) => statuses[s.key] === 'active').length
  const overall = idle && completeCount === 0
    ? 0
    : ((completeCount + activeCount * 0.5) / STAGES.length) * 100

  const currentLabel =
    STAGES.find((s) => statuses[s.key] === 'active')?.label ??
    (completeCount === STAGES.length ? 'Complete' : idle ? 'Idle' : 'Waiting…')

  return (
    <div>
      <div className="pipeline-meta">
        <div>
          <div style={{ fontSize: 11, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: '0.08em', fontWeight: 600 }}>
            Pipeline status
          </div>
          <div style={{ fontSize: 18, fontWeight: 700, letterSpacing: '-0.01em', marginTop: 2 }}>
            {currentLabel}
          </div>
        </div>
        <div className="overall">
          <motion.div
            className="overall-fill"
            animate={{ width: `${overall}%` }}
            transition={{ duration: 0.6, ease: [0.22, 1, 0.36, 1] }}
          />
        </div>
        <div style={{ minWidth: 56, textAlign: 'right', fontVariantNumeric: 'tabular-nums', fontWeight: 700, marginLeft: 12 }}>
          {Math.round(overall)}%
        </div>
      </div>

      <div className="pipeline stagger">
        {STAGES.map((s, i) => {
          const Icon = s.icon
          const status = statuses[s.key]
          const detail = latestDetail(events, s.key) ?? s.detail
          const fill = status === 'complete' ? 100 : status === 'active' ? 60 : 0
          return (
            <motion.div
              key={s.key}
              className={`stage ${status}`}
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: i * 0.04, duration: 0.3, ease: [0.22, 1, 0.36, 1] }}
            >
              <div className="stage-icon">
                <Icon size={18} strokeWidth={2} />
              </div>
              <h4>{s.label}</h4>
              <div className="stage-detail">{detail}</div>
              <div className="stage-bar">
                <motion.div
                  className="stage-bar-fill"
                  animate={{ width: `${fill}%` }}
                  transition={{ duration: 0.6, ease: [0.22, 1, 0.36, 1] }}
                />
              </div>
            </motion.div>
          )
        })}
      </div>
    </div>
  )
}
