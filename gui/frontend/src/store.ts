import { useEffect, useRef, useState } from 'react'
import { api, connectEvents } from './api'
import type { PipelineEvent, VCProfile } from './types'

export function useProfile() {
  const [profile, setProfile] = useState<VCProfile | null>(null)
  const [loading, setLoading] = useState(true)
  useEffect(() => {
    api.getProfile().then((p) => {
      setProfile(p)
      setLoading(false)
    })
  }, [])
  async function save(p: VCProfile) {
    await api.saveProfile(p)
    setProfile(p)
  }
  return { profile, setProfile, save, loading }
}

export function useEventStream() {
  const [events, setEvents] = useState<PipelineEvent[]>([])
  const [activeRunId, setActiveRunId] = useState<string | null>(null)
  const wsRef = useRef<WebSocket | null>(null)

  useEffect(() => {
    const ws = connectEvents((e) => {
      setEvents((prev) => {
        const next = [...prev, e]
        return next.length > 800 ? next.slice(-800) : next
      })
      setActiveRunId(e.run_id)
    })
    wsRef.current = ws
    return () => ws.close()
  }, [])

  return { events, activeRunId, clear: () => setEvents([]) }
}

export function useRunStatus() {
  const [active, setActive] = useState(false)
  useEffect(() => {
    const tick = () => api.runStatus().then((s) => setActive(s.active))
    tick()
    const id = setInterval(tick, 4000)
    return () => clearInterval(id)
  }, [])
  return active
}
