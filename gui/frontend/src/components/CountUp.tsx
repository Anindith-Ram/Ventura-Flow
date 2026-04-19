import { useEffect, useRef, useState } from 'react'

interface Props {
  to: number
  duration?: number
  decimals?: number
  className?: string
  style?: React.CSSProperties
}

export function CountUp({ to, duration = 1000, decimals = 0, className, style }: Props) {
  const [val, setVal] = useState(0)
  const startedAt = useRef<number | null>(null)

  useEffect(() => {
    startedAt.current = null
    let raf = 0
    const step = (ts: number) => {
      if (startedAt.current === null) startedAt.current = ts
      const t = Math.min(1, (ts - startedAt.current) / duration)
      const eased = 1 - Math.pow(1 - t, 3)
      setVal(to * eased)
      if (t < 1) raf = requestAnimationFrame(step)
    }
    raf = requestAnimationFrame(step)
    return () => cancelAnimationFrame(raf)
  }, [to, duration])

  return (
    <span className={className} style={style}>
      {val.toFixed(decimals)}
    </span>
  )
}
