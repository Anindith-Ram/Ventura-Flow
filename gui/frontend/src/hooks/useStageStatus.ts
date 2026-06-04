import { useMemo } from 'react'
import type { PipelineEvent } from '../types'

export type StageStatus = 'pending' | 'running' | 'done' | 'error'

export interface StageState {
  id: string
  label: string
  count: string
  countLabel: string
  status: StageStatus
  startedAt: number | null
  endedAt: number | null
  durationSec: number | null
}

export const STAGE_DEFS: Array<{ id: string; label: string; countKey: string; countLabel: string }> = [
  { id: 'plan',       label: 'Query Planner', countKey: 'queries',         countLabel: 'queries' },
  { id: 'ingest',     label: 'Metadata Ingest',countKey: 'papers_ingested', countLabel: 'papers' },
  { id: 'dedup',      label: 'Dedup',          countKey: 'papers_after_dedup', countLabel: 'unique' },
  { id: 'triage',     label: 'Triage',         countKey: 'papers_triaged', countLabel: 'scored' },
  { id: 'gate',       label: 'Gate',           countKey: 'top_k_selected', countLabel: 'passed' },
  { id: 'deep_ingest',label: 'Deep Ingest',    countKey: 'papers_deep',    countLabel: 'full text' },
  { id: 'analysis',   label: 'Bull/Bear/Judge',countKey: 'judged',         countLabel: 'memos' },
]

function fmt(n: number): string {
  if (n >= 1000) return (n / 1000).toFixed(1) + 'k'
  return String(n)
}

export function useStageStatus(events: PipelineEvent[]): StageState[] {
  return useMemo(() => {
    const stateMap: Record<string, {
      status: StageStatus
      startedAt: number | null
      endedAt: number | null
      count: string
    }> = {}

    for (const def of STAGE_DEFS) {
      stateMap[def.id] = { status: 'pending', startedAt: null, endedAt: null, count: '' }
    }

    for (const ev of events) {
      const s = stateMap[ev.stage]
      if (!s) continue
      const ts = new Date(ev.timestamp).getTime()

      if (ev.level === 'stage_start') {
        s.status = 'running'
        s.startedAt = ts
      } else if (ev.level === 'stage_end') {
        s.status = 'done'
        s.endedAt = ts
        // extract count from data
        const def = STAGE_DEFS.find(d => d.id === ev.stage)
        if (def) {
          const raw = ev.data?.[def.countKey]
          if (typeof raw === 'number') s.count = fmt(raw)
          else if (Array.isArray(raw)) s.count = fmt(raw.length)
        }
      } else if (ev.level === 'error') {
        s.status = 'error'
      }

      // also pick up incremental counts mid-stage
      if (s.status === 'running') {
        const def = STAGE_DEFS.find(d => d.id === ev.stage)
        if (def) {
          const raw = ev.data?.[def.countKey]
          if (typeof raw === 'number') s.count = fmt(raw)
          // running triage counts from per-paper events
          if (ev.stage === 'triage' && typeof ev.data?.paper_id === 'string') {
            // use message parse "N/M"
            const m = ev.message.match(/^\[(\d+)\/\d+\]/)
            if (m) s.count = m[1]
          }
        }
      }
    }

    return STAGE_DEFS.map(def => {
      const s = stateMap[def.id]
      const dur = s.startedAt && s.endedAt
        ? Math.round((s.endedAt - s.startedAt) / 1000)
        : null
      return {
        id: def.id,
        label: def.label,
        count: s.count,
        countLabel: def.countLabel,
        status: s.status,
        startedAt: s.startedAt,
        endedAt: s.endedAt,
        durationSec: dur,
      }
    })
  }, [events])
}
