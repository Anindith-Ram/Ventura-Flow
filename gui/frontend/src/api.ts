import type { PipelineEvent, RunRow, TriageScore, VCProfile, WatchlistRow } from './types'

const base = ''  // same-origin

async function j<T>(url: string, init?: RequestInit): Promise<T> {
  const r = await fetch(base + url, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  })
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`)
  return r.json()
}

export const api = {
  getProfile: () => j<VCProfile>('/api/profile'),
  saveProfile: (p: VCProfile) =>
    j<{ ok: boolean }>('/api/profile', { method: 'PUT', body: JSON.stringify(p) }),
  getTemplates: () => j<Record<string, VCProfile>>('/api/profile/templates'),

  startRun: (payload: Record<string, unknown>) =>
    j<{ ok: boolean; mode: string }>('/api/run/start', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  cancelRun: () => j<{ ok: boolean; cancelled: boolean }>('/api/run/cancel', { method: 'POST' }),
  runStatus: () => j<{ active: boolean }>('/api/run/status'),

  listRuns: () => j<RunRow[]>('/api/runs'),
  getRun: (runId: string) =>
    j<{ run: RunRow; scores: TriageScore[] }>(`/api/runs/${runId}`),
  getPaper: (runId: string, paperId: string) =>
    j<{ paper: any; artefacts: Record<string, unknown>; watchlisted: boolean }>(
      `/api/runs/${runId}/paper/${encodeURIComponent(paperId)}`,
    ),
  reanalyzePaper: (runId: string, paperId: string) =>
    j<{ ok: boolean }>(
      `/api/runs/${runId}/paper/${encodeURIComponent(paperId)}/reanalyze`,
      { method: 'POST', body: JSON.stringify({}) },
    ),
  exportPdfUrl: (runId: string, topK = 10) =>
    `${base}/api/runs/${runId}/export.pdf?top_k=${topK}`,

  listWatchlist: () => j<WatchlistRow[]>('/api/watchlist'),
  addToWatchlist: (paperId: string, sourceRun?: string) =>
    j<{ ok: boolean; watchlisted: boolean }>(
      `/api/watchlist/${encodeURIComponent(paperId)}`,
      { method: 'POST', body: JSON.stringify({ source_run: sourceRun }) },
    ),
  removeFromWatchlist: (paperId: string) =>
    j<{ ok: boolean; watchlisted: boolean }>(
      `/api/watchlist/${encodeURIComponent(paperId)}`,
      { method: 'DELETE' },
    ),

  testDigest: () => j<{ ok: boolean }>('/api/digest/test', { method: 'POST' }),

  recentEvents: (runId?: string) =>
    j<PipelineEvent[]>(`/api/events/recent${runId ? '?run_id=' + runId : ''}`),
}

export function connectEvents(onEvent: (e: PipelineEvent) => void) {
  const scheme = window.location.protocol === 'https:' ? 'wss' : 'ws'
  const ws = new WebSocket(`${scheme}://${window.location.host}/ws/events`)
  ws.onmessage = (msg) => {
    try {
      onEvent(JSON.parse(msg.data))
    } catch {}
  }
  return ws
}
