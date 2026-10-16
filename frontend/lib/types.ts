/**
 * TypeScript types for the frozen API contract (docs/API.md).
 * Keep in sync with the contract, not with backend internals.
 */

export type FeatureValue = 0 | 1 | null;

export type Mode = "calibrated" | "cold_start" | (string & {});

export interface Health {
  status: string;
  model_loaded: boolean;
  llm_provider: string; // "stub" | "gemini" | "openai" | ...
  projects_count: number;
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
  project_id: string;
  findings: Finding[];
  estimate: EstimateRange;
  similar_projects: SimilarProject[];
  questions: VoIQuestion[];
  coefficients: Coefficient[];
  warnings: string[];
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
}

export interface ReplayResponse {
  steps: ReplayStep[];
  summary: ReplaySummary;
}

export type ABMode = "real" | "simulated" | (string & {});

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
