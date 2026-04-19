import { useEffect, useState } from 'react'
import { api } from '../api'
import { useProfile } from '../store'
import type { VCProfile } from '../types'

function ChipList({
  value, onChange, placeholder,
}: {
  value: string[]
  onChange: (next: string[]) => void
  placeholder: string
}) {
  const [draft, setDraft] = useState('')
  function add() {
    const v = draft.trim()
    if (!v) return
    if (value.includes(v)) return
    onChange([...value, v])
    setDraft('')
  }
  return (
    <div>
      <div className="row" style={{ marginBottom: 6 }}>
        {value.map((v) => (
          <span key={v} className="chip">
            {v}
            <button onClick={() => onChange(value.filter((x) => x !== v))}>×</button>
          </span>
        ))}
      </div>
      <div style={{ display: 'flex', gap: 6 }}>
        <input
          placeholder={placeholder}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') {
              e.preventDefault()
              add()
            }
          }}
        />
        <button onClick={add}>Add</button>
      </div>
    </div>
  )
}

export function Preferences() {
  const { profile, setProfile, save, loading } = useProfile()
  const [templates, setTemplates] = useState<Record<string, VCProfile>>({})
  const [saved, setSaved] = useState(false)

  useEffect(() => {
    api.getTemplates().then(setTemplates)
  }, [])

  if (loading || !profile) return <div>Loading profile…</div>

  function update<K extends keyof VCProfile>(key: K, v: VCProfile[K]) {
    setProfile({ ...profile!, [key]: v })
  }

  function applyTemplate(name: string) {
    const tpl = templates[name]
    if (!tpl) return
    setProfile({ ...tpl, updated_at: profile!.updated_at })
  }

  async function handleSave() {
    await save(profile!)
    setSaved(true)
    setTimeout(() => setSaved(false), 1500)
  }

  return (
    <div>
      <div className="header">
        <div>
          <h2>VC Preferences</h2>
          <div className="sub">
            Shapes every query the planner emits and every triage score. Saved globally.
          </div>
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          <button className="primary" onClick={handleSave}>
            {saved ? '✓ Saved' : 'Save'}
          </button>
        </div>
      </div>

      <div className="card">
        <h3>Template</h3>
        <div className="row">
          {Object.keys(templates).map((name) => (
            <button key={name} onClick={() => applyTemplate(name)}>
              {name}
            </button>
          ))}
        </div>
        <p className="sub" style={{ marginTop: 8 }}>
          Templates fill the form with a reasonable starting thesis — fully editable after.
        </p>
      </div>

      <div className="card">
        <h3>Thesis (freetext)</h3>
        <textarea
          value={profile.thesis}
          onChange={(e) => update('thesis', e.target.value)}
          placeholder="Describe what your firm invests in, how you think about edge, and what would make a research paper signal for you. The Query Planner reasons about this directly."
          style={{ minHeight: 140 }}
        />
      </div>

      <div className="grid-2">
        <div className="card">
          <h3>Sectors of interest</h3>
          <ChipList
            value={profile.sectors}
            onChange={(v) => update('sectors', v)}
            placeholder="e.g. carbon capture"
          />
          <label>Stage</label>
          <select
            value={profile.stage}
            onChange={(e) => update('stage', e.target.value as any)}
          >
            <option value="pre-seed">Pre-seed</option>
            <option value="seed">Seed</option>
            <option value="series-a">Series A</option>
            <option value="series-b">Series B</option>
            <option value="growth">Growth</option>
            <option value="any">Any</option>
          </select>
        </div>

        <div className="card">
          <h3>Geography</h3>
          <ChipList
            value={profile.geography}
            onChange={(v) => update('geography', v)}
            placeholder="e.g. US, EU, UK"
          />
          <h3 style={{ marginTop: 20 }}>Deal-breakers</h3>
          <ChipList
            value={profile.deal_breakers}
            onChange={(v) => update('deal_breakers', v)}
            placeholder="e.g. requires clinical trials > $100M"
          />
        </div>
      </div>

      <div className="card">
        <h3>Publication window</h3>
        <div className="grid-2">
          <div>
            <label>From year</label>
            <input
              type="number"
              value={profile.year_from}
              onChange={(e) => update('year_from', +e.target.value)}
            />
          </div>
          <div>
            <label>To year (blank = present)</label>
            <input
              type="number"
              value={profile.year_to ?? ''}
              placeholder="present"
              onChange={(e) =>
                update('year_to', e.target.value ? +e.target.value : null)
              }
            />
          </div>
        </div>
      </div>
    </div>
  )
}
