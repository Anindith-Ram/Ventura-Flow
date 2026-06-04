import { AnimatePresence, motion } from 'framer-motion'
import { useEffect, useRef, useState } from 'react'
import type { PipelineEvent } from '../types'

interface Props {
  events: PipelineEvent[]
  active: boolean
}

const LEVELS = ['all', 'stage_start', 'stage_end', 'warn', 'error', 'success'] as const
type Level = typeof LEVELS[number]

export function EventDrawer({ events, active }: Props) {
  const [open, setOpen] = useState(false)
  const [filter, setFilter] = useState<Level>('all')
  const [seenCount, setSeenCount] = useState(0)
  const termRef = useRef<HTMLDivElement>(null)

  const unread = events.length - seenCount

  useEffect(() => {
    if (open) {
      setSeenCount(events.length)
      setTimeout(() => {
        if (termRef.current) termRef.current.scrollTop = termRef.current.scrollHeight
      }, 50)
    }
  }, [open, events.length])

  useEffect(() => {
    if (open && termRef.current) {
      termRef.current.scrollTop = termRef.current.scrollHeight
    }
  }, [events, open])

  const filtered = filter === 'all'
    ? events
    : events.filter(e => e.level === filter)

  return (
    <>
      {/* FAB */}
      <div className={`event-fab ${active ? '' : 'ghost'}`} onClick={() => setOpen(true)}>
        {active && <span className="dot" />}
        <span>Activity log</span>
        {unread > 0 && <span className="unread">{unread > 99 ? '99+' : unread}</span>}
      </div>

      <AnimatePresence>
        {open && (
          <>
            <motion.div
              className="drawer-backdrop"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.18 }}
              onClick={() => setOpen(false)}
            />
            <motion.div
              className="drawer"
              initial={{ x: '100%' }}
              animate={{ x: 0 }}
              exit={{ x: '100%' }}
              transition={{ type: 'spring', damping: 28, stiffness: 300 }}
            >
              <div className="drawer-header">
                <div>
                  <h3 style={{ margin: 0 }}>Activity Log</h3>
                  <div className="tiny">{events.length} events</div>
                </div>
                <button className="ghost" onClick={() => setOpen(false)} style={{ fontSize: 16 }}>✕</button>
              </div>

              <div className="drawer-filter">
                {LEVELS.map(l => (
                  <button
                    key={l}
                    className={`filter-chip ${filter === l ? 'active' : ''}`}
                    onClick={() => setFilter(l)}
                  >
                    {l === 'all' ? 'All' : l.replace('_', ' ')}
                  </button>
                ))}
              </div>

              <div className="terminal" ref={termRef}>
                {filtered.length === 0 && (
                  <span className="evt info" style={{ color: 'var(--dim)' }}>
                    {events.length === 0 ? 'Waiting for pipeline events…' : 'No events match this filter.'}
                  </span>
                )}
                {filtered.map((e, i) => (
                  <span key={i} className={`evt ${e.level}`}>
                    <span className="ts">{new Date(e.timestamp).toLocaleTimeString()}</span>
                    <span className="stage">{e.stage}</span>
                    {' '}{e.message}
                    {'\n'}
                  </span>
                ))}
              </div>
            </motion.div>
          </>
        )}
      </AnimatePresence>
    </>
  )
}
