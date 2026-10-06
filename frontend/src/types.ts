export type User = { id: string; email: string; role: 'candidate' | 'employer'; email_verified: boolean }

export type AchievementStory = {
  title: string
  context: string
  personal_contribution: string
  decision: string
  result: string
  result_scope: 'individual' | 'team'
  basis: string
  share_with_employers: boolean
  formatted_narrative?: string
}

export type Profile = {
  id?: string
  full_name: string
  contact_email: string
  contact_phone: string
  city: string
  summary: string
  achievement_story?: AchievementStory | null
  skills: string[]
  experience_months: number
  min_salary_rub: number
  work_format: string
  consent_processing: boolean
  published: boolean
  available: boolean
  verified_specialization?: string | null
  verified_grade?: string | null
  test_score?: number | null
  competencies?: Record<string, number>
  fsp_status?: string
  fsp_result?: string | null
  next_grade_change_at?: string | null
}

export type AnswerValue = string | number | Record<string, string | number>
export type Question = {
  id: string
  competency: string
  prompt: string
  points: number
  phase: number
  type: 'choice' | 'number' | 'structured'
  options?: { value: string; label: string }[]
  fields?: { id: string; label: string; points: number; options: { value: string; label: string }[] }[]
}
export type Attempt = {
  id: string
  phase: number
  state: string
  score?: number
  outcome?: string
  questions: Question[]
  answers: Record<string, AnswerValue>
  verified_category?: string
}

export type Need = {
  id: string
  title: string
  description: string
  specialization: string
  grade: string
  salary_min_rub: number
  salary_max_rub: number
  work_format: string
  competencies: string[]
  stack: string[]
  role_version_id: string | null
}

export type InterviewStep = { title: string; duration_minutes: number }
export type RoleCardPayload = {
  title: string
  description: string
  specialization: 'backend' | 'frontend'
  grade: 'junior' | 'middle'
  competencies: string[]
  stack: string[]
  salary_min_rub: number
  salary_max_rub: number
  work_format: 'remote' | 'hybrid' | 'office'
  work_city: string | null
  industry: string | null
  first_30_days: string
  interview_steps: InterviewStep[]
  take_home_minutes: number
  response_sla_hours: 24 | 48 | 72
  employer_contact: string
  active_headcount_attested: boolean
}
export type RoleCardOut = {
  need_id: string
  version: number | null
  schema_version: number | null
  payload: Partial<RoleCardPayload>
  terms_hash: string | null
  source: string | null
  current_role_version: number
  publication_state: 'draft' | 'active' | 'paused' | 'closed'
  discoverable: boolean
  confirmed_at: string | null
  fresh: boolean
  missing_fields: string[]
  salary_currency: 'RUB'
  salary_period: 'month'
  salary_basis: 'gross'
}

export type CandidateRoleCard = Omit<RoleCardPayload, 'employer_contact' | 'active_headcount_attested'>
export type CandidateRoleDecision = 'saved' | 'hidden' | 'none'
export type CandidateRoleFeedItem = {
  need_id: string
  role_version_id: string
  role_version: number
  company_name: string
  role: CandidateRoleCard
  confirmed_at: string
  preferences_version: number
  data_mode: 'real' | 'synthetic' | 'unknown'
  match_state: 'compatible' | 'needs_clarification' | 'not_assessed'
  compatibility: {
    status: 'compatible' | 'needs_clarification' | 'incompatible'
    checks: { code: string; status: 'pass' | 'unknown' | 'fail'; public_text: string }[]
    soft_signals: { code: string; matched: boolean; public_text: string }[]
    preference_version: number
    role_version_id: string | null
    compatibility_version: 'compat_v2'
  } | null
  decision: CandidateRoleDecision
}
export type CandidateRoleFeed = {
  items: CandidateRoleFeedItem[]
  next_cursor: string | null
  limit: number
  empty_state: 'no_active_roles' | 'no_compatible_roles' | 'no_saved_roles' | null
}
export type CandidateRoleDecisionResult = {
  need_id: string
  action: CandidateRoleDecision
  role_version_id: string
  preferences_version: number
  updated_at: string
}

export type Match = {
  score: number | null
  components: Record<string, number | null>
  reasons: string[]
  gaps: string[]
  evidence_coverage?: number
  algorithm_version: string
}
export type Candidate = {
  id: string
  alias: string
  specialization: string
  grade: string
  test_score: number
  competencies: Record<string, number>
  skills_declared: string[]
  fsp_status: string
  bank_score_algorithm_version?: string
  fsp_result?: string | null
  bank_score?: number
  match?: Match
  verification_source?: string
}
export type SearchSummary = {
  id: string
  need_id: string
  parent_snapshot_id: string | null
  role_version_id: string | null
  algorithm_version: string
  created_at: string
  result_count: number
  filters: { fsp_only: boolean; stack: string[] }
}
export type Search = Omit<SearchSummary, 'result_count'> & {
  results: Candidate[]
  unavailable_count: number
  changed_since_search: boolean
}

export type EvidenceCard = {
  id: string
  competency: string | null
  action: string
  source_type: 'assessment_attempt' | 'achievement_story' | 'skill_claim' | 'legacy_aggregate'
  source_id: string | null
  source_version: string
  assessed_at: string | null
  verification_level: 'verified_action' | 'declared' | 'aggregate' | 'synthetic_fixture'
  scope: string
  limitations: string[]
  data_mode: 'real' | 'synthetic'
}
export type CompatibilityReport = {
  status: 'compatible' | 'needs_clarification' | 'incompatible'
  checks: { code: string; status: 'pass' | 'unknown' | 'fail'; public_text: string }[]
  soft_signals: { code: string; matched: boolean; public_text: string }[]
  preference_version: number
  role_version_id: string | null
  compatibility_version: 'compat_v2'
}
export type CandidatePreferences = {
  version: number
  salary_min_rub: number | null
  allowed_work_formats: ('remote' | 'hybrid' | 'office')[]
  allowed_cities: string[]
  excluded_industries: string[]
  preferred_stack: string[]
  preferred_tasks: string[]
  max_take_home_minutes: number | null
  available: boolean
  adult_hiring_confirmed: boolean
}

export type Invite = {
  id: string
  candidate_id: string
  company_name: string
  employer_id: string
  need_id: string | null
  role_version_id: string | null
  offer_text: string
  reason: string
  employer_contact: string
  salary_min_rub: number
  salary_max_rub: number
  salary_period: 'month'
  salary_basis: 'gross'
  work_format: string
  state: 'sent' | 'viewed' | 'accepted' | 'rejected' | 'withdrawn' | 'expired'
  created_at?: string
  expires_at: string
  terms_snapshot?: { role?: Partial<RoleCardPayload>; offer?: Record<string, unknown> } | null
  terms_hash?: string | null
  evidence_refs?: EvidenceCard[]
  explanation_snapshot?: { reasons?: string[]; gaps?: { competency: string; status: string; question: string }[]; agenda?: string[] } | null
  compatibility_at_send?: CompatibilityReport | null
  compatibility?: CompatibilityReport | null
  state_version?: number
  response_due_at?: string | null
}
