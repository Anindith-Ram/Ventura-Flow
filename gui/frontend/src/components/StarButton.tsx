import { Star } from 'lucide-react'
import { useState } from 'react'
import { api } from '../api'

interface Props {
  paperId: string
  runId?: string
  initial: boolean
  size?: number
  onChange?: (watchlisted: boolean) => void
}

export function StarButton({ paperId, runId, initial, size = 16, onChange }: Props) {
  const [on, setOn] = useState(initial)
  const [pending, setPending] = useState(false)

  async function toggle(e: React.MouseEvent) {
    e.preventDefault()
    e.stopPropagation()
    if (pending) return
    setPending(true)
    const next = !on
    setOn(next)
    try {
      if (next) await api.addToWatchlist(paperId, runId)
      else await api.removeFromWatchlist(paperId)
      onChange?.(next)
    } catch {
      setOn(!next)
    } finally {
      setPending(false)
    }
  }

  return (
    <button
      onClick={toggle}
      title={on ? 'Remove from watchlist' : 'Add to watchlist'}
      aria-pressed={on}
      style={{
        padding: 4,
        background: 'transparent',
        border: 'none',
        boxShadow: 'none',
        color: on ? 'var(--coral)' : 'var(--muted-2)',
        cursor: 'pointer',
        display: 'inline-flex',
        alignItems: 'center',
        transition: 'transform 0.15s, color 0.15s',
        transform: on ? 'scale(1.1)' : 'scale(1)',
      }}
    >
      <Star
        size={size}
        strokeWidth={2}
        fill={on ? 'var(--coral)' : 'none'}
      />
    </button>
  )
}
