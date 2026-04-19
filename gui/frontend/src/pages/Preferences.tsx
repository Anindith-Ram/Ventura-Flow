import { Check, Send } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { api } from '../api'
import { useProfile } from '../store'
import type { VCProfile } from '../types'

const INVESTOR_CUES = [
  'invest', 'capital', 'stage', 'seed', 'series', 'market', 'moat', 'scale',
  'defensibility', 'ip', 'patent', 'commercial', 'revenue', 'customer',
  'regulatory', 'barrier', 'edge', 'traction', 'founder', 'team',
]

function thesisHealth(thesis: string): { label: string; color: string; score: number; hint: string } {
  const words = thesis.trim().split(/\s+/).filter(Boolean).length
  const lower = thesis.toLowerCase()
  const cues = INVESTOR_CUES.filter((c) => lower.includes(c)).length
  const score = Math.min(100, words * 1.2 + cues * 8)
  if (words < 20) {
    return { label: 'Too thin', color: 'var(--berry)', score, hint: 'Under 20 words — queries will be generic. Describe sectors, what edge looks like, and what signals you.' }
  }
  if (words < 50 || cues < 3) {
    return { label: 'Workable', color: 'var(--sun)', score, hint: 'Add concrete investor framing — what would make a paper signal for you?' }
  }
  return { label: 'Strong', color: 'var(--seaweed)', score, hint: `${words} words · ${cues} investor cues — planner will generate rich queries.` }
}

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
    if (!v || value.includes(v)) return
    onChange([...value, v])
    setDraft('')
  }
  return (
    <div>
      {value.length > 0 && (
        <div className="row" style={{ marginBottom: 10 }}>
          {value.map((v) => (
            <span key={v} className="chip">
              {v}
              <button onClick={() => onChange(value.filter((x) => x !== v))}>×</button>
            </span>
          ))}
        </div>
      )}
      <div style={{ display: 'flex', gap: 6 }}>
        <input
          placeholder={placeholder}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') { e.preventDefault(); add() }
          }}
        />
        <button onClick={add}>Add</button>
      </div>
    </div>
  )
}

function ThesisCard({ thesis, onChange }: { thesis: string; onChange: (v: string) => void }) {
  const health = useMemo(() => thesisHealth(thesis), [thesis])
  return (
    <div className="card">
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 10 }}>
        <h3 style={{ margin: 0 }}>Thesis</h3>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <span style={{
            display: 'inline-flex', alignItems: 'center', gap: 6,
            padding: '3px 10px', borderRadius: 999,
            background: `color-mix(in srgb, ${health.color} 15%, transparent)`,
            border: `1px solid ${health.color}`,
            color: health.color,
            fontSize: 11, fontWeight: 700, letterSpacing: '0.04em', textTransform: 'uppercase',
          }}>
            <span style={{ width: 6, height: 6, borderRadius: '50%', background: health.color }} />
            {health.label}
          </span>
        </div>
      </div>
      <textarea
        value={thesis}
        onChange={(e) => onChange(e.target.value)}
        placeholder="Describe what your firm invests in, how you think about edge, and what would make a research paper signal for you. The Query Planner reasons about this directly."
        style={{ minHeight: 150 }}
      />
      <div style={{ marginTop: 10, display: 'flex', alignItems: 'center', gap: 10 }}>
        <div className="bar" style={{ flex: 1 }}>
          <div
            className="bar-fill"
            style={{
              width: `${health.score}%`,
              background: `linear-gradient(90deg, var(--sun), ${health.color})`,
              transition: 'width 0.4s',
            }}
          />
        </div>
        <span className="sub" style={{ fontSize: 12, minWidth: 280, textAlign: 'right' }}>
          {health.hint}
        </span>
      </div>
    </div>
  )
}

function WebhookCard({
  value, onChange,
}: { value: string | null; onChange: (v: string | null) => void }) {
  const [testing, setTesting] = useState(false)
  const [msg, setMsg] = useState<string | null>(null)
  async function test() {
    setTesting(true); setMsg(null)
    try {
      const r = await api.testDigest()
      setMsg(r.ok ? 'Sent ✓' : 'Webhook responded with failure')
    } catch (e: any) {
      setMsg(e.message)
    } finally {
      setTesting(false)
      setTimeout(() => setMsg(null), 3500)
    }
  }
  return (
    <div className="card">
      <h3>Post-run digest</h3>
      <p className="sub" style={{ textTransform: 'none', letterSpacing: 0, marginBottom: 12 }}>
        When a run finishes, POST a summary of the top papers to a webhook URL.
        Slack webhooks (URL contains <code>slack.com</code>) get formatted blocks;
        any other URL receives a raw JSON payload.
      </p>
      <label>Webhook URL</label>
      <input
        type="url"
        value={value ?? ''}
        onChange={(e) => onChange(e.target.value || null)}
        placeholder="https://hooks.slack.com/services/..."
      />
      <div style={{ marginTop: 12, display: 'flex', gap: 8, alignItems: 'center' }}>
        <button
          onClick={test}
          disabled={!value || testing}
          style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}
        >
          <Send size={13} strokeWidth={2} />
          {testing ? 'Sending…' : 'Send test digest'}
        </button>
        {msg && <span className="sub" style={{ fontSize: 12 }}>{msg}</span>}
      </div>
    </div>
  )
}

export function Preferences() {
  const { profile, setProfile, save, loading } = useProfile()
  const [templates, setTemplates] = useState<Record<string, VCProfile>>({})
  const [saved, setSaved] = useState(false)

  useEffect(() => { api.getTemplates().then(setTemplates) }, [])

  if (loading || !profile) return <div className="sub">Loading profile…</div>

  function update<K extends keyof VCProfile>(key: K, v: VCProfile[K]) {
    setProfile({ ...profile!, [key]: v })
  }

  function applyTemplate(name: string) {
    const tpl = templates[name]
    if (!tpl) return
    setProfile({
      ...tpl,
      user_name: profile!.user_name,
      firm_name: profile!.firm_name,
      updated_at: profile!.updated_at,
    })
  }

  async function handleSave() {
    await save(profile!)
    setSaved(true)
    setTimeout(() => setSaved(false), 1800)
  }

  return (
    <div>
      <div className="header">
        <div>
          <h2>Preferences</h2>
          <div className="sub">
            Shapes every query the planner emits and every triage score. Saved globally.
          </div>
        </div>
        <button className="primary" onClick={handleSave} style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
          {saved ? <><Check size={14} strokeWidth={3} /> Saved</> : 'Save'}
        </button>
      </div>

      <div className="card">
        <h3>Identity</h3>
        <div className="grid-2">
          <div>
            <label>Your name</label>
            <input
              value={profile.user_name}
              onChange={(e) => update('user_name', e.target.value)}
              placeholder="Ada Lovelace"
            />
          </div>
          <div>
            <label>Firm name</label>
            <input
              value={profile.firm_name}
              onChange={(e) => update('firm_name', e.target.value)}
              placeholder="Analytical Engines Capital"
            />
          </div>
        </div>
      </div>

      <div className="card">
        <h3>Template</h3>
        <div className="row">
          {Object.keys(templates).map((name) => (
            <button
              key={name}
              onClick={() => applyTemplate(name)}
              className={profile.template === name ? 'primary' : ''}
            >
              {name}
            </button>
          ))}
        </div>
        <p className="sub" style={{ marginTop: 10 }}>
          Templates fill the form with a reasonable starting thesis — fully editable after.
        </p>
      </div>

      <ThesisCard thesis={profile.thesis} onChange={(v) => update('thesis', v)} />

      <div className="grid-2">
        <div className="card">
          <h3>Sectors of interest</h3>
          <ChipList
            value={profile.sectors}
            onChange={(v) => update('sectors', v)}
            placeholder="e.g. carbon capture"
          />
          <label>Stage</label>
          <select value={profile.stage} onChange={(e) => update('stage', e.target.value as any)}>
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
            <input type="number" value={profile.year_from} onChange={(e) => update('year_from', +e.target.value)} />
          </div>
          <div>
            <label>To year (blank = present)</label>
            <input
              type="number"
              value={profile.year_to ?? ''}
              placeholder="present"
              onChange={(e) => update('year_to', e.target.value ? +e.target.value : null)}
            />
          </div>
        </div>
      </div>

      <WebhookCard
        value={profile.digest_webhook_url}
        onChange={(v) => update('digest_webhook_url', v)}
      />
    </div>
  )
}
