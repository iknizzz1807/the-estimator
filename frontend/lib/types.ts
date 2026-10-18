/**
 * TypeScript types for the frozen API contract (docs/API.md).
 * Keep in sync with the contract, not with backend internals.
 */

export type FeatureValue = 0 | 1 | null;

export type Mode = "calibrated" | "cold_start" | (string & {});

/** "mc" = Monte Carlo interval over unknown features; "point" = fully known. */
export type EstimateMethod = "mc" | "point" | (string & {});

/** Accumulated yes/no answers for POST /api/estimate (contract v0.2). */
export type AnswersMap = Record<string, 0 | 1>;

export interface Health {
  status: string;
  model_loaded: boolean;
  llm_provider: string; // "stub" | "gemini" | "openai" | ...
  projects_count: number;
  /** Codebase Lab capabilities: the UI must not offer what the host cannot serve. */
  codebase?: {
    choices: string[];
    /** False in cloud builds (no .git in the image — DECISIONS D17). */
    self_available: boolean;
    /** True when pasted public GitHub URLs may be cloned (guarded). */
    url_clone: boolean;
    /** Pre-cloned example repos present on this host (click = instant result). */
    examples?: Array<{
      id: string;
      repo: string;
      label: string;
      lang: string;
      kind: string;
      pinned_date?: string;
    }>;
  };
}

export interface Finding {
  name: string;
  value: FeatureValue; // 1 = present, 0 = absent, null = unknown
  confidence: number; // 0..1
  evidence_quote: string | null;
}

export interface EstimateRange {
  p10: number;
  p50: number;
  p90: number;
  unit: string; // "days"
  mode: Mode;
  /** Optional in v0.1 payloads; v0.2 always sends it. */
  method?: EstimateMethod;
}

export interface SimilarProject {
  project_id: string;
  title_hint: string;
  score: number; // 0..1
  actual_days: number;
  shared_features: string[];
}

export interface VoIQuestion {
  feature: string;
  impact_days: number;
  question_vi: string;
  question_en: string;
}

export interface Coefficient {
  feature: string;
  multiplier: number;
  sample_count: number;
}

export interface EstimateResponse {
  /** null on answer-refinement calls (contract v0.2: side-effect free, no new row). */
  project_id: string | null;
  findings: Finding[];
  estimate: EstimateRange;
  similar_projects: SimilarProject[];
  questions: VoIQuestion[];
  coefficients: Coefficient[];
  warnings: string[];
  /** Codebase Lab block (contract v0.2); present only when `repo` was sent. */
  codebase?: CodebaseBlock;
  /**
   * Set instead of `codebase` when the repository could not be analysed (missing
   * .git, clone failed, too large). The estimate itself is unaffected — a
   * codebase problem is never fatal (DECISIONS D20).
   */
  codebase_error?: string;
}

/* ---------------------- Codebase Lab (contract v0.2) ---------------------- */

/**
 * Repository selector for POST /api/estimate (`repo` body field): a built-in id
 * ("demo_a" | "demo_b" | "self") or a pasted public repo — a GitHub URL
 * (`https://github.com/<owner>/<repo>`) or the `<owner>/<repo>` shorthand.
 * The server canonicalises and validates it (only github.com is accepted).
 */
export type RepoChoice = string;

export type FrictionLevel = "low" | "medium" | "high" | (string & {});

export interface CodebaseFriction {
  /** Weighted structural friction score in 0..1. */
  score: number;
  level: FrictionLevel;
  /** churn / fan_in / complexity / coverage_gap / author_concentration; null = unknown (never faked). */
  components: Record<string, number | null>;
}

export interface CodebaseInvasiveness {
  /** Share of similar-change files that were modifications (vs new files). */
  modified_ratio: number;
  mean_files_touched: number;
  based_on_commits: number;
}

export interface CodebaseSimilarChange {
  commit: string;
  date: string;
  files_touched: number;
  new_files: number;
  modified_files: number;
}

export interface CodebaseAdjustment {
  what: string;
  factor: number;
  why: string;
}

export interface CodebaseBlock {
  repo: string;
  /** Which language was analysed. Codebase Lab is Python-only (D24). */
  language?: {
    dominant: string;
    python_files: number;
    source_files: number;
    python_share: number;
  };
  friction: CodebaseFriction;
  /** null when no similar past changes matched — no evidence, no median shift. */
  invasiveness: CodebaseInvasiveness | null;
  /** Up to 5 newest similar past changes (date + patch shape). */
  similar_changes: CodebaseSimilarChange[];
  base_estimate: EstimateRange;
  /** The top-level `estimate` carries exactly these numbers. */
  adjusted_estimate: EstimateRange;
  adjustments: CodebaseAdjustment[];
  /** Honest-limitations note — surfaced verbatim. */
  note: string;
}

export interface ProjectRow {
  project_id: string;
  date: string;
  status: string; // "done" | "in_progress" | "pending" | ...
  team_estimate: number | null;
  system_p50: number | null;
  /** Optional in the contract; shown as a range when the backend provides it. */
  system_p10?: number | null;
  system_p90?: number | null;
  actual_days: number | null;
  delta_pct: number | null;
  features: Record<string, FeatureValue>;
}

export interface CoefficientUpdate {
  feature: string;
  old: number;
  new: number;
  sample_count: number;
}

export interface ActualUpdateResponse {
  project: ProjectRow;
  coefficient_updates: CoefficientUpdate[];
  accuracy: { mae_before: number; mae_after: number; coverage_pct: number };
  /** Present when actual_days > 1000 (accepted with a warning). */
  warning?: string;
}

export interface ReplayStep {
  i: number;
  project_id: string;
  p10: number;
  p50: number;
  p90: number;
  actual: number;
  mae_system: number;
  mae_team: number;
  /** Optional per-step LLM-only baseline; when absent the UI draws the summary value. */
  mae_llm_only?: number | null;
  in_interval: boolean;
}

export interface ReplaySummary {
  mae_system: number;
  mae_team: number;
  mae_llm_only: number;
  coverage_pct: number;
  llm_only_mode?: "real" | "simulated" | null;
  /** Total walk-forward steps the summary was computed over (v0.2 extra). */
  n_steps?: number | null;
}

export interface ReplayResponse {
  steps: ReplayStep[];
  summary: ReplaySummary;
}

export type ABMode = "real" | "simulated" | (string & {});

/** LLM + company-history baseline inside the A/B response (contract v0.2). */
export interface HistoryBaseline {
  values: number[];
  mean: number;
  std: number;
  n: number;
  mode: ABMode;
  /** Extras the backend may include; ignored when absent. */
  min?: number;
  max?: number;
  errors?: number;
  note?: string;
}

export interface ABResponse {
  mode: ABMode;
  values: number[];
  mean: number;
  std: number;
  min: number;
  max: number;
  system_estimate: number;
  delta_pct: number;
  note: string;
  /** Optional extras / v0.2 additions. */
  n?: number;
  errors?: number;
  provider?: string;
  baseline_history?: HistoryBaseline | null;
}

/* ------------------------- Contract additions v0.2 ------------------------ */

export interface QuotePackage {
  tier: "core" | "standard" | "full" | (string & {});
  label: string;
  estimate: EstimateRange;
  /** P(actual > budget) under the tier's predictive distribution (0..1). */
  over_budget_prob: number | null;
  features_included: Record<string, FeatureValue>;
  excluded: string[];
  notes: string;
}

export interface PricingCurvePoint {
  days: number;
  /** P(actual days > days) under the interval's lognormal fit (0..1). */
  over_prob: number;
}

/** Interactive pricing curve, fitted from the Full-scope interval (v0.2). */
export interface PricingBlock {
  /** Scope the interval was fitted from — always "full". */
  scope: string;
  p10: number;
  p50: number;
  p90: number;
  /** ~25 log-spaced points spanning [p10 * 0.6, p90 * 1.5]. */
  curve: PricingCurvePoint[];
  /** Smallest quotes keeping P(overrun) ≤ 25% / ≤ 10%. */
  safe_quote_25: number;
  safe_quote_10: number;
}

export interface PackagesResponse {
  budget_days: number | null;
  packages: QuotePackage[];
  recommendation: string;
  /** "mc" | "point" — how the tier intervals were produced. */
  method?: EstimateMethod;
  /** Present when every tier exceeds the 25% over-budget threshold. */
  recommendation_note?: string;
  /** v0.2 pricing curve; optional so older payloads still render. */
  pricing?: PricingBlock;
}

export interface ResetResponse {
  status: string;
  projects_count: number;
}

export interface ImportResponse {
  imported: number;
  skipped: number;
  errors: string[];
}

export interface Scenario {
  id: string;
  title: string;
  email_text: string;
  notes?: string;
}

export const STREAM_STEPS = [
  "extracting",
  "validating",
  "similar",
  "estimating",
  "questions",
  "done",
] as const;

export type StreamStep = (typeof STREAM_STEPS)[number];

export interface StreamEvent {
  type: "step" | "result" | "error";
  step?: string;
  message?: string;
  result?: EstimateResponse;
}
