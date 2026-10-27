export interface Page<T> {
  items: T[]
  total: number
  page: number
  page_size: number
}

export interface Me {
  id: string
  full_name: string
  email: string
  role: string
  is_active: boolean
  created_at: string
  permissions: string[]
}

export type User = Omit<Me, 'permissions'>

export interface UserBrief {
  id: string
  full_name: string
}

export interface Author {
  id?: string
  author_name: string
  author_order?: number
  author_email?: string | null
  affiliation?: string | null
}

export interface VersionBrief {
  id: string
  version_number: number
  original_filename: string
  source_format: string
  file_size_bytes: number
  sha256_checksum: string
  extraction_status: string
  extraction_quality: string | null
  uploaded_at: string
}

export interface ExtractionWarning {
  code: string
  message: string
  severity: 'info' | 'warning' | 'error'
  details: Record<string, unknown>
}

export interface ExtractionSummary {
  error?: { code: string; message: string; kind: string }
  char_count?: number
  word_count?: number
  block_count?: number
  block_counts?: Record<string, number>
  page_count?: number | null
  page_numbers_reliable?: boolean
  page_count_source?: 'pdf' | 'word_app_properties' | 'page_breaks' | null
  chapters?: Chapter[]
  toc_entries?: { block_id: string; title: string; page_label: string }[]
  headings?: { block_id: string; level: number; text: string; page_number: number | null; section_path: string | null }[]
  metadata?: Record<string, unknown>
  warnings?: ExtractionWarning[]
  quality?: { score: number; status: string; reasons: string[] }
}

export interface Chapter {
  block_id: string
  number: number | null
  label: string
  title: string | null
  page_number: number | null
  page_estimate: number | null
  section_path: string | null
}

export interface Version extends VersionBrief {
  manuscript_id: string
  mime_type: string
  extraction_engine_version: string | null
  extraction_summary_json: ExtractionSummary
  extraction_started_at: string | null
  extraction_completed_at: string | null
  uploader: UserBrief | null
  supersedes_version_id: string | null
  warnings: string[]
}

export interface ManuscriptListItem {
  id: string
  internal_code: string
  working_title: string
  manuscript_type: string
  language_code: string
  intake_status: string
  submitted_at: string | null
  created_at: string
  assigned_editor: UserBrief | null
  authors: Author[]
  latest_version: VersionBrief | null
  incomplete_fields: string[]
  latest_screening: ScreeningBrief | null
  latest_layout: ScreeningBrief | null
}

export interface Manuscript extends ManuscriptListItem {
  metadata_json: Record<string, unknown>
  creator: UserBrief
  updated_at: string
  versions: VersionBrief[]
}

export interface Section {
  id: string
  block_id: string
  parent_section_id: string | null
  section_type: string
  heading_level: number | null
  section_path: string | null
  paragraph_index: number
  page_number: number | null
  text_content: string
  char_start: number
  char_end: number
  locator_json: Record<string, unknown>
}

export interface AuditEntry {
  id: string
  actor_user_id: string | null
  actor_name: string | null
  manuscript_id: string | null
  event_type: string
  entity_type: string
  entity_id: string | null
  before_json: Record<string, unknown> | null
  after_json: Record<string, unknown> | null
  ip_address: string | null
  created_at: string
}

export interface Option {
  value: string
  label: string
}

export interface Options {
  manuscript_types: Option[]
  languages: Option[]
  intake_statuses: string[]
  extraction_statuses: Option[]
  distribution_options: Option[]
}

export interface ScreeningBrief {
  id: string
  status: string
  isbn_status: string | null
  editorial_status: string | null
  total_score: number | null
  findings_total: number | null
  by_severity: Record<string, number>
  completed_at: string | null
}

export interface ScreeningRun {
  id: string
  manuscript_id: string
  document_version_id: string
  run_number: number
  status: string
  isbn_status: string | null
  editorial_status: string | null
  total_score: string | null
  trigger: string
  scope: 'isbn' | 'layout' | 'full'
  queued_at: string
  started_at: string | null
  completed_at: string | null
  engine_version: string
  version_number: number
  rule_set: { id: string; name: string; version: number }
  rubric: {
    id: string
    name: string
    version: number
    manuscript_type: string
    min_scoring_coverage: number
    thresholds: { pass?: number; minor_revision?: number; major_revision?: number }
  } | null
  result_summary_json: {
    findings_total?: number
    by_severity?: Record<string, number>
    by_track?: Record<string, number>
    isbn_counts?: Record<string, number>
    rule_errors?: string[]
    rules_run?: number
    rules_not_applicable?: number
    score?: { total: number | null; coverage: number; scored: number; applicable: number; reasons: string[] } | null
    chapters?: number
    pages?: number | null
    verification?: Record<string, number> & { total: number; reviewed: number }
    layout?: LayoutSummary | null
    classification?: Classification | null
    resolved_previous?: number
  }
  error_details: { code: string; message: string } | null
  final_decision: string | null
  decided_at: string | null
  decision_note: string | null
  recalculated_at: string | null
  disclaimer: string
}

export interface FindingItem {
  id: string
  rule_code: string
  track: 'editorial' | 'compliance'
  category: string
  severity: 'critical' | 'major' | 'minor' | 'info'
  criterion_code: string | null
  title: string
  description: string
  evidence_excerpt: string | null
  page_number: number | null
  page_estimate: number | null
  section_path: string | null
  paragraph_id: string | null
  suggested_action: string | null
  requires_human_verification: boolean
  blocking: boolean
  verification_status: string
  reviewed_by: string | null
  reviewed_at: string | null
  review_note: string | null
  machine_result_json: { details?: Record<string, unknown>; rule_title?: string }
}

export interface FindingFacets {
  severity: Record<string, number>
  track: Record<string, number>
  category: Record<string, number>
  rule_code: Record<string, number>
  chapter: { section_path: string | null; count: number }[]
}

export interface ComplianceItem {
  id: string
  rule_code: string
  title: string
  observed: string
  result_status: string
  authority_type: string
  rule_verification_status: string
  blocking: boolean
  evidence_json: Record<string, unknown>
  explanation: string | null
  requires_human_verification: boolean
  manual_observed: string | null
  manual_note: string | null
  verified_at: string | null
  source_title: string | null
  source_url: string | null
  source_reference: string | null
}

export interface ScoreRow {
  criterion_code_snapshot: string | null
  criterion_name_snapshot: string | null
  result_type: 'criterion' | 'total'
  raw_score: string | null
  weight_percent: string
  weighted_contribution: string | null
  scoring_status: string
  evidence_coverage: string | null
  explanation: string | null
  calculation_details_json: {
    rules?: {
      rule_code: string
      title: string
      applicable: boolean
      findings_counted?: number
      deduction?: number
      deduction_per_finding?: number
      max_deduction?: number
    }[]
    total_deduction?: number
    formula?: string
    reasons?: string[]
  }
}

export interface RuleItem {
  id: string
  rule_code: string
  title: string
  description: string | null
  category: string
  track: string
  authority_type: string
  source_title: string | null
  source_url: string | null
  source_reference: string | null
  verification_status: string
  verified_at: string | null
  verification_note: string | null
  applies_to_types: string[] | null
  engine_key: string
  config_json: Record<string, unknown>
  severity: string
  blocking: boolean
  requires_human_verification: boolean
  scoring_effect: { criterion_code?: string; deduction_per_finding?: number; max_deduction?: number }
  execution_order: number
  status: string
  updated_at: string
}

export interface RuleSetItemOut {
  id: string
  name: string
  version: number
  status: string
  description: string | null
  change_notes: string | null
  published_at: string | null
  created_at: string
  test_results_json: {
    runs?: {
      at: string
      file: string
      manuscript_type: string
      isbn_status: string
      editorial_status: string | null
      total: number | null
      findings: number
      errors: string[]
    }[]
  } | null
  items_count: number
}

export interface RubricItem {
  id: string
  name: string
  version: number
  manuscript_type: string
  status: string
  min_scoring_coverage: string
  score_thresholds_json: { pass?: number; minor_revision?: number; major_revision?: number; note?: string }
  change_notes: string | null
  published_at: string | null
  created_at: string
  criteria: { id: string; criterion_code: string; name: string; description: string | null; weight_percent: string; required_for_scoring: boolean }[]
}

export interface ReviewLogItem {
  id: string
  action_type: string
  actor_name: string | null
  previous_status: string | null
  new_status: string | null
  comment: string | null
  finding_id: string | null
  compliance_check_id: string | null
  created_at: string
  evidence_json: Record<string, unknown> | null
}

export interface DecisionInfo {
  recommendation: string
  accept_blockers: string[]
  is_latest: boolean
  verification: Record<string, number> & { total: number; reviewed: number }
  note: string
  final_decision: string | null
  decided_at: string | null
  decided_by: string | null
  decision_note: string | null
  history: ReviewLogItem[]
  can_decide: boolean
}

export interface ComparisonFinding {
  id: string
  rule_code: string
  severity: string
  title: string
  section_path: string | null
  verification_status: string
}

export interface Comparison {
  previous: {
    run_id: string
    version_number: number
    total_score: number | null
    isbn_status: string | null
    editorial_status: string | null
    findings: number
  }
  current: { run_id: string; version_number: number; total_score: number | null; isbn_status: string | null; editorial_status: string | null; findings: number }
  resolved: ComparisonFinding[]
  new: ComparisonFinding[]
  persisting: ComparisonFinding[]
  rule_set_changed: boolean
  rubric_changed: boolean
}

export interface LayoutShare {
  value: string | number
  chars?: number
  share: number
}

export interface LayoutSummary {
  supported: boolean
  format?: 'docx' | 'pdf'
  reason?: string
  pages?: number | null
  page_sizes?: { width_cm: number; height_cm: number; count: number; where: string[]; landscape: number }[]
  margins?: { where: string; top: number; bottom: number; left: number; right: number }[]
  page_numbers?: { present: boolean; method: string }
  body_fonts?: LayoutShare[]
  body_sizes?: LayoutShare[]
  line_spacing?: LayoutShare[]
  alignment?: LayoutShare[]
  images?: { name: string; dpi: number | null; where: string }[]
  fonts_embedded?: { all: boolean; not_embedded: Record<string, number[]> } | null
  blank_pages?: number[] | null
}

export interface ClassItem {
  value: string
  label?: string
  confidence: 'tinggi' | 'sedang' | 'rendah'
  reasons: string[]
}

export interface Classification {
  source: string
  jenis_terbitan: ClassItem
  jenis_pustaka: ClassItem
  kelompok_pembaca: ClassItem
  kategori_buku: ClassItem
  terjemahan: ClassItem
  penelitian: ClassItem
  kategori_penerbit: ClassItem
  peredaran?: ClassItem
  media: ClassItem
  applied: boolean
  manual_type: string | null
}
