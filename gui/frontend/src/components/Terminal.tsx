import { useEffect, useRef } from 'react'
import type { PipelineEvent } from '../types'

export function Terminal({ events }: { events: PipelineEvent[] }) {
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (ref.current) ref.current.scrollTop = ref.current.scrollHeight
  }, [events])

  return (
    <div className="terminal" ref={ref}>
      {events.length === 0 && (
        <span className="evt info" style={{ color: '#6b7280' }}>
          Waiting for pipeline events…
        </span>
      )}
      {events.map((e, i) => (
        <span key={i} className={`evt ${e.level}`}>
          <span className="ts">{new Date(e.timestamp).toLocaleTimeString()}</span>
          <span className="stage">{e.stage}</span>
          {' '}
          {e.message}
        </span>
      ))}
    </div>
  )
}
