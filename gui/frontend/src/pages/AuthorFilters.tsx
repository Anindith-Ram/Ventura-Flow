import { useState } from 'react'
import { useProfile } from '../store'
import type { VCProfile } from '../types'

function Slider({
  label, value, onChange, step = 0.05, min = 0, max = 1, hint,
}: {
  label: string
  value: number
  onChange: (v: number) => void
  step?: number
  min?: number
  max?: number
  hint?: string
}) {
  return (
    <div style={{ marginTop: 14 }}>
      <label style={{ marginTop: 0 }}>{label}</label>
      {hint && <div className="sub" style={{ fontSize: 11, marginBottom: 4 }}>{hint}</div>}
      <div className="slider-row">
        <input
          type="range" min={min} max={max} step={step}
          value={value} onChange={(e) => onChange(+e.target.value)}
        />
        <span className="val">{(value * 100).toFixed(0)}%</span>
      </div>
    </div>
  )
}

export function AuthorFilters() {
  const { profile, setProfile, save, loading } = useProfile()
  const [saved, setSaved] = useState(false)

  if (loading || !profile) return <div>Loading profile…</div>

  function update<K extends keyof VCProfile>(key: K, v: VCProfile[K]) {
    setProfile({ ...profile!, [key]: v })
  }

  // Normalise weights to sum to 1.0 so the user sees a percentage mix.
  const sum = profile.weight_vc_fit + profile.weight_novelty + profile.weight_author_credibility
  const norm = (v: number) => (sum > 0 ? v / sum : 0)

  async function handleSave() {
    // Normalise before saving so downstream math is consistent.
    const s =
      profile!.weight_vc_fit + profile!.weight_novelty + profile!.weight_author_credibility
    if (s > 0) {
      setProfile({
        ...profile!,
        weight_vc_fit: profile!.weight_vc_fit / s,
        weight_novelty: profile!.weight_novelty / s,
        weight_author_credibility: profile!.weight_author_credibility / s,
      })
    }
    await save({
      ...profile!,
      weight_vc_fit: profile!.weight_vc_fit / (s || 1),
      weight_novelty: profile!.weight_novelty / (s || 1),
      weight_author_credibility: profile!.weight_author_credibility / (s || 1),
    })
    setSaved(true)
    setTimeout(() => setSaved(false), 1500)
  }

  return (
    <div>
      <div className="header">
        <div>
          <h2>Author Filters & Weights</h2>
          <div className="sub">
            Hard filters miss breakthrough papers from junior researchers. These are weights,
            not gates — strong papers from low-h-index authors can still surface.
          </div>
        </div>
        <button className="primary" onClick={handleSave}>
          {saved ? '✓ Saved' : 'Save'}
        </button>
      </div>

      <div className="card">
        <h3>Triage composite weights</h3>
        <p className="sub">
          How much each dimension contributes to the final score. Normalised on save; currently
          showing {(norm(profile.weight_vc_fit) * 100).toFixed(0)}% / {(norm(profile.weight_novelty) * 100).toFixed(0)}% / {(norm(profile.weight_author_credibility) * 100).toFixed(0)}%.
        </p>

        <Slider
          label="VC-fit weight"
          hint="How well the paper matches the thesis"
          value={profile.weight_vc_fit}
          onChange={(v) => update('weight_vc_fit', v)}
        />
        <Slider
          label="Novelty weight"
          hint="How original the contribution is"
          value={profile.weight_novelty}
          onChange={(v) => update('weight_novelty', v)}
        />
        <Slider
          label="Author credibility weight"
          hint="Author track record — h-index, citations, works count"
          value={profile.weight_author_credibility}
          onChange={(v) => update('weight_author_credibility', v)}
        />
      </div>

      <div className="card">
        <h3>Soft h-index floor</h3>
        <p className="sub">
          Applied as a ±2–3 point composite modifier — not a hard filter. Set to 0 to disable.
        </p>
        <input
          type="number" min={0} max={100}
          value={profile.min_h_index}
          onChange={(e) => update('min_h_index', +e.target.value)}
        />
      </div>
    </div>
  )
}
