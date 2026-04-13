export type DrawingType =
  | 'external'
  | 'parts'
  | 'internal_layout'
  | 'single_line'
  | 'expanded'
  | 'sequence_logic'
  | 'unknown'

export const DRAWING_TYPE_LABELS: Record<DrawingType, string> = {
  external: '外形図',
  parts: '部品図',
  internal_layout: '内部部品配置図',
  single_line: '単線結線図',
  expanded: '展開接続図',
  sequence_logic: 'シーケンスロジック図',
  unknown: '不明',
}

export type ProjectStatus =
  | 'pending'
  | 'extracting'
  | 'estimating'
  | 'confirmed'
  | 'analyzing'
  | 'done'
  | 'error'

export interface DrawingFile {
  id: string
  filename: string
  drawing_type: DrawingType
  page_count: number
  annotated_path: string | null
  created_at: string
}

export interface Project {
  id: string
  name: string
  status: ProjectStatus
  estimated_input_tokens: number
  estimated_output_tokens: number
  estimated_cost_usd: number
  actual_input_tokens: number
  actual_output_tokens: number
  actual_cost_usd: number
  created_at: string
  files: DrawingFile[]
}

export interface CostEstimate {
  file_count: number
  total_pages: number
  estimated_input_tokens: number
  estimated_output_tokens: number
  estimated_cost_usd: number
  free_tier_note: string
}

export interface CheckResult {
  id: string
  check_type: string
  severity: 'error' | 'warning' | 'ok' | 'uncertain'
  file_id: string | null
  page_number: number | null
  location_rect: [number, number, number, number] | null
  message: string
  detail: Record<string, unknown> | null
}

export interface UncertainItem {
  file_id: string
  page: number
  text: string
  reason: string
  rect?: [number, number, number, number] | null
}

export interface AnalysisResult {
  project_id: string
  status: ProjectStatus
  cost: {
    actual_input_tokens: number
    actual_output_tokens: number
    actual_cost_usd: number
    model: string
    free_tier_note: string
  }
  check_results: CheckResult[]
  uncertain_items: UncertainItem[]
}

export const CHECK_TYPE_LABELS: Record<string, string> = {
  tag_consistency: 'Tag.No整合',
  customer_name: '顧客名称',
  relay_cross_ref: 'リレー参照',
  electrical_spec: '電気諸元',
  breaker_rating: '遮断器定格',
  cross_check: 'ファイル間整合',
  logic_integrity: 'ロジック整合',
  verified: '確認済み',
  uncertain: 'AI判断困難',
}
