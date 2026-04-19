export interface VCProfile {
  user_name: string
  firm_name: string
  digest_webhook_url: string | null
  thesis: string
  sectors: string[]
  stage: 'pre-seed' | 'seed' | 'series-a' | 'series-b' | 'growth' | 'any'
  geography: string[]
  deal_breakers: string[]
  weight_vc_fit: number
  weight_novelty: number
  weight_author_credibility: number
  min_h_index: number
  year_from: number
  year_to: number | null
  template: string | null
  updated_at: string
}

export interface TriageScore {
  paper_id: string
  title: string
  vc_fit: number
  novelty: number
  credibility: number
  composite: number
  rationale: string
  subfield: string
  has_memo: boolean
}

export interface RunRow {
  run_id: string
  mode: string
  started_at: string
  finished_at: string | null
  queries_planned: number
  papers_ingested: number
  papers_passed_triage: number
  papers_deep_analyzed: number
  top_paper_ids: string
  artifacts_dir: string
  score_distribution?: number[]
}

export interface WatchlistRow {
  paper_id: string
  title: string | null
  added_at: string
  note: string | null
  source_run: string | null
}

export interface PipelineEvent {
  run_id: string
  stage: string
  level: 'info' | 'warn' | 'error' | 'success' | 'stage_start' | 'stage_end'
  message: string
  data: Record<string, unknown>
  timestamp: string
}
