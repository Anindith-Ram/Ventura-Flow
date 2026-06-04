import { motion } from 'framer-motion'
import React, { useEffect, useState } from 'react'
import { useStageStatus } from '../hooks/useStageStatus'
import type { PipelineEvent } from '../types'

interface Props {
  events: PipelineEvent[]
}

export function PipelineDAG({ events }: Props) {
  const stages = useStageStatus(events)

  return (
    <div style={{ overflowX: 'auto', paddingBottom: 4 }}>
      <div
        className="dag"
        style={{ '--n': stages.length } as React.CSSProperties}
      >
        {stages.map((stage, i) => (
          <motion.div
            key={stage.id}
            className={`dag-node ${stage.status}`}
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: i * 0.04, duration: 0.25 }}
          >
            <div className="stage-head">
              <span className="stage-name">
                <span className="stage-dot" />
                {stage.label}
              </span>
              <span className="stage-idx">{i + 1}</span>
            </div>

            <div className="stage-count">
              {stage.count
                ? stage.count
                : stage.status === 'pending'
                ? '—'
                : stage.status === 'running'
                ? <RunningDots />
                : '—'}
            </div>

            <div className="stage-meta">
              <span style={{ color: stage.count ? 'var(--muted)' : 'transparent' }}>
                {stage.countLabel}
              </span>
              <span>
                {stage.durationSec != null
                  ? `${stage.durationSec}s`
                  : stage.status === 'running'
                  ? <Elapsed since={stage.startedAt} />
                  : ''}
              </span>
            </div>
          </motion.div>
        ))}
      </div>
    </div>
  )
}

function RunningDots() {
  return (
    <span style={{ fontSize: 14, letterSpacing: 2 }}>
      <motion.span
        animate={{ opacity: [0.3, 1, 0.3] }}
        transition={{ duration: 1.2, repeat: Infinity, delay: 0 }}
      >·</motion.span>
      <motion.span
        animate={{ opacity: [0.3, 1, 0.3] }}
        transition={{ duration: 1.2, repeat: Infinity, delay: 0.4 }}
      >·</motion.span>
      <motion.span
        animate={{ opacity: [0.3, 1, 0.3] }}
        transition={{ duration: 1.2, repeat: Infinity, delay: 0.8 }}
      >·</motion.span>
    </span>
  )
}

function Elapsed({ since }: { since: number | null }) {
  const [sec, setSec] = useState(0)

  useEffect(() => {
    if (!since) return
    const tick = () => setSec(Math.floor((Date.now() - since) / 1000))
    tick()
    const id = setInterval(tick, 1000)
    return () => clearInterval(id)
  }, [since])

  return <>{sec}s</>
}
