interface Props {
  values: number[]
  width?: number
  height?: number
  color?: string
  fillColor?: string
}

export function Sparkline({
  values, width = 120, height = 28,
  color = 'var(--coral)', fillColor = 'rgba(201, 100, 66, 0.12)',
}: Props) {
  if (!values.length) {
    return <span className="sub" style={{ fontSize: 11 }}>—</span>
  }
  const pad = 2
  const w = width - pad * 2
  const h = height - pad * 2
  const maxY = 100  // triage composite is 0–100
  const minY = 0
  const step = values.length > 1 ? w / (values.length - 1) : 0
  const y = (v: number) => pad + h - ((v - minY) / (maxY - minY)) * h
  const pts = values.map((v, i) => `${pad + i * step},${y(v)}`).join(' ')
  const areaPts = `${pad},${pad + h} ${pts} ${pad + w},${pad + h}`
  const last = values[0]  // values are sorted desc — first is top score
  return (
    <svg width={width} height={height} style={{ display: 'block' }}>
      <polygon points={areaPts} fill={fillColor} />
      <polyline points={pts} fill="none" stroke={color} strokeWidth={1.5}
        strokeLinecap="round" strokeLinejoin="round" />
      <circle cx={pad} cy={y(last)} r={2.5} fill={color} />
    </svg>
  )
}
