import { Check } from 'lucide-react'
import { useState } from 'react'
import { useProfile } from '../store'
import type { VCProfile } from '../types'

function Slider({
  label, value, onChange, step = 0.05, min = 0, max = 1, hint,
}: {
  label: string; value: number; onChange: (v: number) => void
  step?: number; min?: number; max?: number; hint?: string
}) {
  return (
    <div style={{ marginTop: 16 }}>
      <label style={{ marginTop: 0 }}>{label}</label>
      {hint && <div className="sub" style={{ fontSize: 12, marginBottom: 6, textTransform: 'none', letterSpacing: 0 }}>{hint}</div>}
      <div className="slider-row">
        <input type="range" min={min} max={max} step={step} value={value} onChange={(e) => onChange(+e.target.value)} />
        <span className="val">{(value * 100).toFixed(0)}%</span>
      </div>
    </div>
  )
}

export function AuthorFilters() {
  const { profile, setProfile, save, loading } = useProfile()
  const [saved, setSaved] = useState(false)

  if (loading || !profile) return <div className="sub">Loading profile…</div>

  function update<K extends keyof VCProfile>(key: K, v: VCProfile[K]) {
    setProfile({ ...profile!, [key]: v })
  }

  const sum = profile.weight_vc_fit + profile.weight_novelty + profile.weight_author_credibility
  const norm = (v: number) => (sum > 0 ? v / sum : 0)

  async function handleSave() {
    const s = profile!.weight_vc_fit + profile!.weight_novelty + profile!.weight_author_credibility
    const normalized = {
      ...profile!,
      weight_vc_fit: profile!.weight_vc_fit / (s || 1),
      weight_novelty: profile!.weight_novelty / (s || 1),
      weight_author_credibility: profile!.weight_author_credibility / (s || 1),
    }
    setProfile(normalized)
    await save(normalized)
    setSaved(true)
    setTimeout(() => setSaved(false), 1800)
  }

  const pcts = {
    vc_fit: (norm(profile.weight_vc_fit) * 100).toFixed(0),
    novelty: (norm(profile.weight_novelty) * 100).toFixed(0),
    cred: (norm(profile.weight_author_credibility) * 100).toFixed(0),
  }

  return (
    <div>
      <div className="header">
        <div>
          <h2>Weights & author filters</h2>
          <div className="sub">
            Hard filters miss breakthrough papers from junior researchers. These are weights —
            strong papers from low-h-index authors still surface.
          </div>
        </div>
        <button className="primary" onClick={handleSave} style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
          {saved ? <><Check size={14} strokeWidth={3} /> Saved</> : 'Save'}
        </button>
      </div>

      <div className="card">
        <h3>Triage composite weights</h3>
        <p className="sub" style={{ textTransform: 'none', letterSpacing: 0 }}>
          Currently mixed <strong>{pcts.vc_fit}%</strong> VC fit ·{' '}
          <strong>{pcts.novelty}%</strong> novelty · <strong>{pcts.cred}%</strong> credibility.
          Normalised on save.
        </p>

        {/* Live bar preview */}
        <div style={{ display: 'flex', height: 12, borderRadius: 999, overflow: 'hidden', margin: '14px 0 4px', background: 'var(--panel-2)' }}>
          <div style={{ width: `${pcts.vc_fit}%`, background: 'var(--coral)', transition: 'width 0.4s' }} />
          <div style={{ width: `${pcts.novelty}%`, background: 'var(--sun)', transition: 'width 0.4s' }} />
          <div style={{ width: `${pcts.cred}%`, background: 'var(--seaweed)', transition: 'width 0.4s' }} />
        </div>

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
        <p className="sub" style={{ textTransform: 'none', letterSpacing: 0 }}>
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
