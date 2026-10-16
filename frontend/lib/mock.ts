/**
 * Contract-shaped mock payloads (docs/API.md) so every screen renders fully
 * with NEXT_PUBLIC_USE_MOCK=1 — or automatically when the backend is offline.
 *
 * The mock estimate is a tiny deterministic keyword extractor, not a random
 * fixture: same email in → same estimate out, which keeps the demo honest
 * about the "consistent output" KPI (spec §7.2).
 */

import { FEATURES } from "./features";
import type {
  ABResponse,
  ActualUpdateResponse,
  AnswersMap,
  CodebaseBlock,
  CodebaseSimilarChange,
  Coefficient,
  EstimateRange,
  EstimateResponse,
  Finding,
  FeatureValue,
  Health,
  ImportResponse,
  PackagesResponse,
  PricingBlock,
  PricingCurvePoint,
  ProjectRow,
  RepoChoice,
  ReplayResponse,
  ReplayStep,
  ResetResponse,
  Scenario,
  SimilarProject,
  StreamEvent,
  VoIQuestion,
} from "./types";

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

function hashText(s: string): number {
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return Math.abs(h);
}

/* ------------------------------------------------------------------ */
/* Tiny deterministic extractor for mock estimates                     */
/* ------------------------------------------------------------------ */

const FEATURE_PATTERNS: Record<string, RegExp> = {
  third_party_api:
    /third[- ]party api|external api|api integration|crm|erp|partner'?s api|banking partner/i,
  payment_gateway:
    /payment|checkout|billing|stripe|vnpay|momo|refund|chargeback|subscriptions?|thanh toán/i,
  identity_provider: /sso|oauth|identity provider|azure ad|okta|đăng nhập|sign in/i,
  external_data_sync:
    /sync(hroniz|hronis)?|two-way data|warehouse|đồng bộ|keep records in sync/i,
  data_migration:
    /migrat|legacy data|spreadsheets?|chuyển dữ liệu|migration dữ liệu/i,
  multi_currency:
    /multi[- ]currency|multiple currencies|exchange rate|foreign currency|tỷ giá|loại tiền tệ/i,
  multi_tenancy: /multi[- ]tenant|tenant workspace|per-tenant|tenants? isolated/i,
  realtime_ui:
    /real[- ]time|live (notifications|dashboard|updates)|under 100ms|<100ms|websocket|cập nhật tức thời/i,
  mobile_app:
    /mobile app|native (ios|android)|ios and android|app store|ứng dụng mobile|android devices/i,
  offline_mode: /offline|without internet|lose their connection|mất kết nối|local storage/i,
  pci_dss: /pci[- ]?dss|cardholder data|card data/i,
  privacy_compliance:
    /gdpr|hipaa|privacy compliance|right to deletion|privacy requirements|quyền xóa dữ liệu/i,
  audit_logging: /audit/i,
  legacy_tech_stack:
    /legacy|cobol|mainframe|on[- ]prem|old languages|công nghệ cũ/i,
  cross_team_coordination:
    /cross[- ]team|multiple teams|coordination|another (supplier|team)|second supplier|internal it|nhiều team|phối hợp/i,
};

const NEGATION =
  /\b(no|not|never|without|isn'?t|doesn'?t|does not|don'?t|won'?t|cannot|can'?t|no longer)\b|không|chưa|miễn phí/i;

function sentences(email: string): string[] {
  return email
    .split(/[.!?\n]+/)
    .map((s) => s.trim())
    .filter((s) => s.length > 3);
}

function findEvidence(
  email: string,
  pattern: RegExp
): { sentence: string; negated: boolean } | null {
  const global = new RegExp(pattern.source, pattern.flags.includes("i") ? "i" : "");
  for (const sentence of sentences(email)) {
    if (!global.test(sentence)) continue;
    const lower = sentence.toLowerCase();
    const matchIndex = lower.search(
      new RegExp(pattern.source.toLowerCase())
    );
    const window = lower.slice(Math.max(0, matchIndex - 40), matchIndex + 60);
    return { sentence, negated: NEGATION.test(window) };
  }
  return null;
}

const QUESTION_TEXT: Record<string, { en: string; vi: string }> = {
  third_party_api: {
    en: "Which external systems or APIs does the product need to integrate with (CRM, ERP, partner systems) — and roughly how many?",
    vi: "Sản phẩm cần tích hợp với những hệ thống/API bên ngoài nào (CRM, ERP, đối tác) — khoảng bao nhiêu hệ thống?",
  },
  payment_gateway: {
    en: "Will the product process payments? Through which gateway and methods (cards, wallets, transfers)?",
    vi: "Sản phẩm có xử lý thanh toán không? Qua cổng nào và phương thức nào (thẻ, ví, chuyển khoản)?",
  },
  identity_provider: {
    en: "Will users sign in with local accounts or via SSO/OAuth (customer's identity provider)? More than one provider?",
    vi: "Người dùng đăng nhập bằng tài khoản nội bộ hay qua SSO/OAuth (IdP của khách)? Cần nhiều nhà cung cấp không?",
  },
  external_data_sync: {
    en: "Which external systems need continuous two-way data sync, and how often (real-time, hourly, daily)?",
    vi: "Dữ liệu cần đồng bộ hai chiều với hệ thống ngoài nào và tần suất bao lâu (thời gian thực, mỗi giờ, hàng ngày)?",
  },
  data_migration: {
    en: "Is data migration from existing systems required? Roughly how many records and in what format?",
    vi: "Có cần chuyển dữ liệu từ hệ thống cũ không? Khoảng bao nhiêu bản ghi và định dạng hiện tại là gì?",
  },
  multi_currency: {
    en: "Does the app need multiple currencies, including exchange-rate conversion and historical rates?",
    vi: "Ứng dụng có cần hỗ trợ nhiều loại tiền tệ, quy đổi tỷ giá và lịch sử tỷ giá không?",
  },
  multi_tenancy: {
    en: "Single-customer deployment or one platform shared by multiple tenants? What data-isolation level is required?",
    vi: "Triển khai cho một khách hay nhiều khách trên cùng nền tảng (multi-tenant)? Mức tách biệt dữ liệu yêu cầu là gì?",
  },
  realtime_ui: {
    en: "Does the UI need sub-100ms real-time updates (live dashboard)? Which screens?",
    vi: "Giao diện có cần cập nhật tức thời dưới 100ms (dashboard trực tiếp) không? Những màn hình nào?",
  },
  mobile_app: {
    en: "Are native mobile apps required (iOS/Android), or is responsive web enough? App-store release needed?",
    vi: "Có cần ứng dụng mobile native (iOS/Android) hay web responsive là đủ? Có cần phát hành qua app store không?",
  },
  offline_mode: {
    en: "Must the app work without connectivity? Which flows and how long offline, with sync on reconnect?",
    vi: "Ứng dụng có cần hoạt động khi mất kết nối? Luồng nào, offline bao lâu, có đồng bộ lại khi online không?",
  },
  pci_dss: {
    en: "Does the project touch cardholder data (PCI-DSS scope)? Who owns the compliance audit?",
    vi: "Dự án có chạm dữ liệu thẻ (phạm vi PCI-DSS) không? Bên nào chịu trách nhiệm audit tuân thủ?",
  },
  privacy_compliance: {
    en: "Which privacy regime applies (GDPR/HIPAA)? Any data-residency or right-to-deletion requirements?",
    vi: "Áp dụng quy định bảo mật nào (GDPR/HIPAA)? Có yêu cầu data residency hay quyền xóa dữ liệu không?",
  },
  audit_logging: {
    en: "Is a detailed audit trail required (who changed what, when)? How long must it be retained?",
    vi: "Có yêu cầu audit trail chi tiết (ai đổi gì, khi nào) không? Thời gian lưu trữ bao lâu?",
  },
  legacy_tech_stack: {
    en: "Any legacy constraints — old languages, on-premise systems, or systems we must not replace?",
    vi: "Có ràng buộc công nghệ cũ nào — ngôn ngữ cũ, hệ thống on-prem, hay hệ thống không được thay thế?",
  },
  cross_team_coordination: {
    en: "Which teams or vendors must we coordinate with, and who owns integration points?",
    vi: "Cần phối hợp với những team/nhà cung cấp nào, và ai sở hữu các điểm tích hợp?",
  },
};

function mockExtractFindings(emailText: string): Finding[] {
  const email = emailText || "";
  const base = hashText(email);
  return FEATURES.map((name, index) => {
    const hit = findEvidence(email, FEATURE_PATTERNS[name]);
    let value: FeatureValue = null;
    let confidence = 0.3;
    let evidence: string | null = null;
    if (hit) {
      value = hit.negated ? 0 : 1;
      confidence = value === 1 ? 0.86 + ((base + index * 7) % 9) / 100 : 0.62 + ((base + index * 3) % 8) / 100;
      evidence = hit.sentence.length > 160 ? `${hit.sentence.slice(0, 157).trimEnd()}…` : hit.sentence;
    }
    return {
      name,
      value,
      confidence: Math.min(0.97, Number(confidence.toFixed(2))),
      evidence_quote: evidence,
    };
  });
}

const CANDIDATE_PROJECTS: Array<{
  project_id: string;
  title_hint: string;
  score: number;
  actual_days: number;
  features: string[];
}> = [
  {
    project_id: "P014",
    title_hint: "Bank partner onboarding & payments portal",
    score: 0.86,
    actual_days: 40,
    features: ["payment_gateway", "third_party_api", "pci_dss", "identity_provider"],
  },
  {
    project_id: "P022",
    title_hint: "B2B logistics tracking with external sync",
    score: 0.8,
    actual_days: 46,
    features: ["external_data_sync", "realtime_ui", "third_party_api"],
  },
  {
    project_id: "P007",
    title_hint: "Field inspection mobile app (offline-first)",
    score: 0.75,
    actual_days: 33,
    features: ["mobile_app", "offline_mode", "audit_logging"],
  },
  {
    project_id: "P031",
    title_hint: "Multi-tenant SaaS billing platform",
    score: 0.72,
    actual_days: 58,
    features: ["multi_tenancy", "multi_currency", "audit_logging"],
  },
  {
    project_id: "P045",
    title_hint: "Legacy COBOL data migration to cloud",
    score: 0.69,
    actual_days: 52,
    features: ["data_migration", "legacy_tech_stack", "cross_team_coordination"],
  },
];

const MOCK_COEFFICIENTS: Coefficient[] = [
  { feature: "data_migration", multiplier: 1.48, sample_count: 41 },
  { feature: "payment_gateway", multiplier: 1.41, sample_count: 37 },
  { feature: "mobile_app", multiplier: 1.38, sample_count: 29 },
  { feature: "pci_dss", multiplier: 1.34, sample_count: 26 },
  { feature: "multi_tenancy", multiplier: 1.31, sample_count: 24 },
  { feature: "third_party_api", multiplier: 1.29, sample_count: 52 },
  { feature: "external_data_sync", multiplier: 1.27, sample_count: 33 },
  { feature: "legacy_tech_stack", multiplier: 1.26, sample_count: 31 },
  { feature: "cross_team_coordination", multiplier: 1.23, sample_count: 44 },
  { feature: "realtime_ui", multiplier: 1.22, sample_count: 28 },
  { feature: "offline_mode", multiplier: 1.2, sample_count: 22 },
  { feature: "identity_provider", multiplier: 1.18, sample_count: 39 },
  { feature: "audit_logging", multiplier: 1.16, sample_count: 27 },
  { feature: "multi_currency", multiplier: 1.14, sample_count: 25 },
  { feature: "privacy_compliance", multiplier: 1.11, sample_count: 34 },
];

export function mockEstimate(
  emailText: string,
  answers?: AnswersMap,
  repo?: RepoChoice | null
): EstimateResponse {
  const resolved = answers ?? {};
  const findings = mockExtractFindings(emailText).map((finding) => {
    const answer = resolved[finding.name];
    if (answer === undefined) return finding;
    // A direct answer overrides extraction; no evidence quote is invented.
    return { ...finding, value: answer as FeatureValue, confidence: 0.95 };
  });
  const initialUnknown = mockExtractFindings(emailText).filter(
    (f) => f.value === null
  ).length;
  const present = findings.filter((f) => f.value === 1);
  const unknown = findings.filter((f) => f.value === null);
  const base = 17 + present.length * 4.2;
  const jitter = ((hashText(emailText) % 7) - 3) / 100;
  const p50 = Math.max(10, Math.round(base * (1 + jitter)));
  // Offline emulation of the backend Monte-Carlo interval: the range widens
  // with every unknown feature and shrinks by ~18% per answered question
  // (contract v0.2 "answer a question → interval shrinks").
  const answeredCount = Math.max(0, initialUnknown - unknown.length);
  const spread =
    (0.3 + 0.035 * initialUnknown) * Math.pow(0.82, answeredCount);
  const p10 = Math.max(5, Math.round(p50 * (1 - spread)));
  const p90 = Math.round(p50 * (1 + spread * 1.12));
  const baseEstimate: EstimateRange = {
    p10,
    p50,
    p90,
    unit: "days",
    mode: "calibrated",
    method: unknown.length > 0 ? "mc" : "point",
  };

  const questions: VoIQuestion[] = unknown
    .map((f) => ({
      feature: f.name,
      impact_days: Math.max(
        3,
        Math.round(p50 * 1.16 - p50 * 0.93) + (hashText(f.name) % 4)
      ),
      question_en: QUESTION_TEXT[f.name]?.en ?? `Is ${f.name} required?`,
      question_vi:
        QUESTION_TEXT[f.name]?.vi ?? `${f.name} có bắt buộc không?`,
    }))
    .sort((a, b) => b.impact_days - a.impact_days)
    .slice(0, 5);

  const presentNames = new Set(present.map((f) => f.name));
  const similar: SimilarProject[] = CANDIDATE_PROJECTS.map((candidate) => {
    const shared = candidate.features.filter((f) => presentNames.has(f));
    return {
      project_id: candidate.project_id,
      title_hint: candidate.title_hint,
      score: Math.min(0.95, candidate.score + shared.length * 0.02),
      actual_days: candidate.actual_days,
      shared_features: shared,
    };
  })
    .sort((a, b) => b.score - a.score)
    .slice(0, 3);

  const warnings: string[] = [];
  if (emailText.length > 10000) {
    warnings.push(
      "The email is very long (>10,000 characters) — extraction accuracy may drop."
    );
  }
  if (present.length === 0) {
    warnings.push("No features were detected — please review the email before using this estimate.");
  }

  const response: EstimateResponse = {
    project_id: "P061",
    findings,
    estimate: baseEstimate,
    similar_projects: similar,
    questions,
    coefficients: MOCK_COEFFICIENTS,
    warnings,
  };

  // Codebase Lab (contract v0.2): the adjusted estimate replaces the base at
  // the top level; the block carries the base for the before/after visual.
  if (repo) {
    const block = mockCodebaseBlock(repo, baseEstimate);
    response.codebase = block;
    response.estimate = block.adjusted_estimate;
  }
  return response;
}

/* ------------------------------------------------------------------ */
/* Codebase Lab block (contract v0.2) — mirrors the backend formulas   */
/* ------------------------------------------------------------------ */

const MOCK_CODEBASE_NOTE =
  "DEMO-ASSUMED coefficients; the similar-past-changes mechanism is validated on 29k real commits (docs/CODEBASE_HISTORY_VALIDATION.md); no text-prediction accuracy claim (docs/CODEBASE_VALIDATION.md). One-directional by design: surcharge only, never a discount.";

interface MockCodebaseSeed {
  friction: { score: number; level: string; components: Record<string, number | null> };
  invasiveness: { modified_ratio: number; mean_files_touched: number; based_on_commits: number } | null;
  similar_changes: CodebaseSimilarChange[];
}

/** Values below mirror real analyzer output on the deterministic demo repos. */
const MOCK_CODEBASE_SEEDS: Record<string, MockCodebaseSeed> = {
  demo_a: {
    friction: {
      score: 0.111,
      level: "low",
      components: {
        churn: 0.0,
        fan_in: 0.5,
        complexity: 0.1,
        coverage_gap: 0.06,
        author_concentration: 0.0,
      },
    },
    invasiveness: { modified_ratio: 0.3636, mean_files_touched: 2.2, based_on_commits: 5 },
    similar_changes: [
      { commit: "ac035ed", date: "2026-02-01", files_touched: 2, new_files: 1, modified_files: 1 },
      { commit: "b1a2c3d", date: "2026-01-15", files_touched: 2, new_files: 0, modified_files: 2 },
      { commit: "d4e5f60", date: "2025-12-01", files_touched: 2, new_files: 1, modified_files: 1 },
      { commit: "9c8b7a6", date: "2025-11-10", files_touched: 3, new_files: 3, modified_files: 0 },
      { commit: "5f4e3d2", date: "2025-11-02", files_touched: 2, new_files: 2, modified_files: 0 },
    ],
  },
  demo_b: {
    friction: {
      score: 0.3958,
      level: "medium",
      components: {
        churn: 0.0,
        fan_in: 0.875,
        complexity: 0.75,
        coverage_gap: null,
        author_concentration: 0.0,
      },
    },
    invasiveness: { modified_ratio: 0.8571, mean_files_touched: 5.44, based_on_commits: 9 },
    similar_changes: [
      { commit: "e1d1767", date: "2026-03-10", files_touched: 6, new_files: 0, modified_files: 6 },
      { commit: "a7c4b21", date: "2026-03-02", files_touched: 6, new_files: 0, modified_files: 6 },
      { commit: "3e9d5c8", date: "2026-02-18", files_touched: 5, new_files: 0, modified_files: 5 },
      { commit: "f2b6a09", date: "2026-02-05", files_touched: 4, new_files: 1, modified_files: 3 },
      { commit: "8d1f4e3", date: "2026-01-20", files_touched: 7, new_files: 0, modified_files: 7 },
    ],
  },
  self: {
    friction: {
      score: 0.42,
      level: "medium",
      components: {
        churn: 0.55,
        fan_in: 0.5,
        complexity: 0.45,
        coverage_gap: null,
        author_concentration: 0.2,
      },
    },
    invasiveness: { modified_ratio: 0.61, mean_files_touched: 4.1, based_on_commits: 8 },
    similar_changes: [
      { commit: "c3d7e11", date: "2026-10-10", files_touched: 5, new_files: 2, modified_files: 3 },
      { commit: "6a2b8f4", date: "2026-10-02", files_touched: 4, new_files: 1, modified_files: 3 },
      { commit: "90e5c27", date: "2026-09-24", files_touched: 3, new_files: 0, modified_files: 3 },
    ],
  },
};

/**
 * Offline codebase block: same DEMO-ASSUMED transforms as the backend
 * (friction widens p10/p90, invasiveness shifts p50; one-directional only).
 */
function mockCodebaseBlock(repo: RepoChoice, base: EstimateRange): CodebaseBlock {
  const seed = MOCK_CODEBASE_SEEDS[repo] ?? MOCK_CODEBASE_SEEDS.demo_b;
  const score = seed.friction.score;
  const p10Factor = Math.max(0.55, 1 - 0.3 * score);
  const p90Factor = Math.min(1.9, 1 + 0.6 * score);
  const p50Factor = seed.invasiveness
    ? Math.min(1.5, 1 + 0.35 * seed.invasiveness.modified_ratio)
    : 1;
  const adjustedP10 = Math.max(3, Number((base.p10 * p10Factor).toFixed(1)));
  const adjustedP90 = Math.max(base.p90, Number((base.p90 * p90Factor).toFixed(1)));
  const adjustedP50 = Math.min(
    adjustedP90,
    Math.max(adjustedP10, Number((base.p50 * p50Factor).toFixed(1)))
  );
  const adjusted: EstimateRange = {
    ...base,
    p10: adjustedP10,
    p50: adjustedP50,
    p90: adjustedP90,
  };
  const modifiedRatio = seed.invasiveness?.modified_ratio;
  return {
    repo,
    friction: seed.friction,
    invasiveness: seed.invasiveness,
    similar_changes: seed.similar_changes.slice(0, 5),
    base_estimate: base,
    adjusted_estimate: adjusted,
    adjustments: [
      {
        what: "p10 (lower tail)",
        factor: Number(p10Factor.toFixed(4)),
        why: `friction widens the interval downward; median untouched (friction level ${seed.friction.level}, score ${score})`,
      },
      {
        what: "p90 (upper tail)",
        factor: Number(p90Factor.toFixed(4)),
        why: `friction widens the interval upward; median untouched (friction level ${seed.friction.level}, score ${score})`,
      },
      {
        what: "p50 (median)",
        factor: Number(p50Factor.toFixed(4)),
        why:
          modifiedRatio === undefined
            ? "no similar past changes found: no evidence, so the median is unchanged"
            : `similar changes were ${modifiedRatio} modified (not new) files: invasiveness shifts the median (demo-assumed x (1 + 0.35 * ratio))`,
      },
    ],
    note: MOCK_CODEBASE_NOTE,
  };
}

/* ------------------------------------------------------------------ */
/* Budget-fit quote packages (contract v0.2)                           */
/* ------------------------------------------------------------------ */

/** Standard normal CDF (Zelen & Severo approximation, |error| < 7.5e-8). */
function normalCdf(z: number): number {
  const t = 1 / (1 + 0.2316419 * Math.abs(z));
  const density = 0.3989422804014327 * Math.exp((-z * z) / 2);
  const tail =
    density *
    t *
    (0.319381530 +
      t *
        (-0.356563782 +
          t * (1.781477937 + t * (-1.821255978 + t * 1.330274429))));
  return z >= 0 ? 1 - tail : tail;
}

/** Lognormal over-budget probability — same approximation as the backend. */
function overBudgetProb(
  estimate: EstimateRange,
  budgetDays: number
): number {
  const { p10, p50, p90 } = estimate;
  let probability: number;
  if (budgetDays > 0 && p10 > 0 && p90 > p10 && p50 > 0) {
    const sigma = (Math.log(p90) - Math.log(p10)) / (2 * 1.2816);
    const z = (Math.log(budgetDays) - Math.log(p50)) / sigma;
    probability = 1 - normalCdf(z);
  } else {
    probability = budgetDays < p50 ? 1 : 0;
  }
  return Number(Math.min(0.999, Math.max(0.001, probability)).toFixed(3));
}

const PACKAGE_CUTTABLES = [
  "offline_mode",
  "mobile_app",
  "realtime_ui",
  "multi_currency",
  "external_data_sync",
  "audit_logging",
];
const TIER_CUTS: Record<string, number> = { core: 2, standard: 1, full: 0 };
const TIER_LABELS: Record<string, string> = {
  core: "Essential",
  standard: "Standard",
  full: "Full scope",
};
const RISK_NOTE =
  "all packages exceed the 25% over-budget threshold; Essential (core) is the minimum-risk scope — renegotiate the budget or timeline";

/**
 * Contract v0.2 `pricing` block: ~25 log-spaced {days, over_prob} points from
 * p10*0.6 to p90*1.5 plus the smallest safe quotes at 25% / 10% risk — the
 * same lognormal fit the tier probabilities use (mirrors the backend).
 */
function mockPricingBlock(estimate: EstimateRange): PricingBlock {
  const { p10, p50, p90 } = estimate;
  const mu = Math.log(Math.max(p50, 0.1));
  const sigma =
    p10 > 0 && p90 > p10 ? (Math.log(p90) - Math.log(p10)) / (2 * 1.2816) : 0;
  const start = Math.max(0.1, p10 > 0 ? p10 * 0.6 : p50 * 0.6);
  const end = Math.max(start * 1.0001, p90 > 0 ? p90 * 1.5 : start * 2.5);
  const logStart = Math.log(start);
  const step = (Math.log(end) - logStart) / 24;
  const curve: PricingCurvePoint[] = Array.from({ length: 25 }, (_, index) => {
    const days = Math.max(
      0.1,
      Number(Math.exp(logStart + step * index).toFixed(1))
    );
    return { days, over_prob: overBudgetProb(estimate, days) };
  });
  return {
    scope: "full",
    p10,
    p50,
    p90,
    curve,
    safe_quote_25: Number(Math.exp(mu + 0.6745 * sigma).toFixed(1)),
    safe_quote_10: Number(Math.exp(mu + 1.2816 * sigma).toFixed(1)),
  };
}

export async function mockEstimatePackages(
  emailText: string,
  budgetDays: number
): Promise<PackagesResponse> {
  await sleep(850);
  const base = mockEstimate(emailText);
  const multiplier = new Map(
    MOCK_COEFFICIENTS.map((coefficient) => [
      coefficient.feature,
      coefficient.multiplier,
    ])
  );
  const order = new Map(PACKAGE_CUTTABLES.map((name, index) => [name, index]));
  const ranked = PACKAGE_CUTTABLES.filter(
    (name) => base.findings.find((f) => f.name === name)?.value === 1
  ).sort((a, b) => {
    const diff =
      (multiplier.get(b) ?? 1) - (multiplier.get(a) ?? 1);
    return diff !== 0 ? diff : (order.get(a) ?? 0) - (order.get(b) ?? 0);
  });

  const unknownCount = base.findings.filter((f) => f.value === null).length;
  const spread = 0.3 + 0.035 * unknownCount;

  const packages = (["core", "standard", "full"] as const).map((tier) => {
    const cut = ranked.slice(0, TIER_CUTS[tier]);
    const factor = cut.reduce(
      (acc, name) => acc * (1 / (multiplier.get(name) ?? 1.2)),
      1
    );
    const p50 = Math.max(6, Math.round(base.estimate.p50 * factor));
    const estimate: EstimateRange = {
      p10: Math.max(3, Math.round(p50 * (1 - spread))),
      p50,
      p90: Math.round(p50 * (1 + spread * 1.12)),
      unit: "days",
      mode: "calibrated",
      method: unknownCount > 0 ? "mc" : "point",
    };
    const features_included: Record<string, FeatureValue> = {};
    for (const name of FEATURES) {
      const value =
        base.findings.find((f) => f.name === name)?.value ?? null;
      features_included[name] = cut.includes(name) ? 0 : value;
    }
    const notes =
      cut.length === 0
        ? tier === "full"
          ? "full scope: nothing phased out"
          : "no phaseable optional capabilities detected; equivalent to Full scope"
        : `phased scope: drop the ${
            cut.length === 1 ? "highest-impact" : `top-${cut.length} highest-impact`
          } optional ${cut.length === 1 ? "capability" : "capabilities"} (${cut.join(", ")})`;
    return {
      tier,
      label: TIER_LABELS[tier],
      estimate,
      over_budget_prob: overBudgetProb(estimate, budgetDays),
      features_included,
      excluded: cut,
      notes,
    };
  });

  let recommendation = "core";
  let recommendationNote: string | undefined;
  for (const pkg of [...packages].reverse()) {
    if (pkg.over_budget_prob !== null && pkg.over_budget_prob <= 0.25) {
      recommendation = pkg.tier;
      recommendationNote = undefined;
      break;
    }
    recommendationNote = RISK_NOTE;
  }

  const response: PackagesResponse = {
    budget_days: budgetDays,
    packages,
    recommendation,
    method: unknownCount > 0 ? "mc" : "point",
    // Fitted from the Full-scope interval (last package), like the backend.
    pricing: mockPricingBlock(packages[packages.length - 1].estimate),
  };
  if (recommendationNote) response.recommendation_note = recommendationNote;
  return response;
}

export async function mockReset(): Promise<ResetResponse> {
  await sleep(700);
  return { status: "ok", projects_count: 240 };
}

export async function mockEstimateStream(
  emailText: string,
  onEvent: (event: StreamEvent) => void,
  signal?: AbortSignal,
  repo?: RepoChoice | null
): Promise<void> {
  const steps = ["extracting", "validating", "similar", "estimating", "questions", "done"];
  for (const step of steps) {
    await sleep(260);
    if (signal?.aborted) return;
    onEvent({ type: "step", step });
  }
  await sleep(220);
  if (signal?.aborted) return;
  onEvent({ type: "result", result: mockEstimate(emailText, undefined, repo) });
}

/* ------------------------------------------------------------------ */
/* Static endpoints                                                    */
/* ------------------------------------------------------------------ */

export function mockHealth(): Health {
  return {
    status: "ok",
    model_loaded: true,
    llm_provider: "stub",
    projects_count: 240,
  };
}

const SCENARIO_A_EMAIL = `Hello,

We are a licensed payments institution building a new merchant onboarding portal and we need an engineering partner.

Scope highlights:
- Process one-time card payments and monthly subscriptions through an external gateway (we are leaning towards Stripe, but the decision is open).
- PCI-DSS compliance is mandatory because we will handle cardholder data directly.
- The portal must integrate with our CRM and with our banking partner's REST API.
- Live notifications and a real-time risk dashboard are important for the operations team; updates under 100ms matter here.
- We handle personal data of EU residents, so GDPR compliance is a hard requirement.

Not in scope for now: we do not need native mobile apps, and there is no continuous data synchronization with external systems planned for phase one.

We would like to sign with a partner within 6 weeks and start delivery soon after.

Best regards,
Head of Digital, Meridian Pay`;

const SCENARIO_B_EMAIL = `Hi,

We are a B2B SaaS company rebuilding our analytics platform and looking for an engineering partner.

Key requirements:
- Multi-tenant architecture where each client workspace is isolated but shares the same codebase and feature flags.
- Users from our enterprise clients must sign in through their own identity providers (SSO via Azure AD and Okta).
- Detailed audit logging across the platform with a searchable history; this is an enterprise procurement requirement.
- GDPR level privacy compliance for our customers in Europe.
- The warehouse stays as-is: no continuous data synchronization with external systems in this phase. Normal dashboards are fine; there is no real-time or live UI requirement.

No payments processing is involved and there is no PCI scope.

We are flexible on the stack as long as it stays maintainable.`;

const SCENARIO_C_EMAIL = `Xin chào,

Chúng tôi là công ty bảo hiểm quản lý giám định hiện trường, đang tìm đối tác phát triển ứng dụng cho nhân viên hiện trường.

Yêu cầu chính:
- Cần ứng dụng mobile native cho cả iOS và Android (không phải web responsive).
- Nhân viên thường làm việc ở tầng hầm và vùng nông thôn nên ứng dụng phải hoạt động được khi mất kết nối (offline mode dùng local storage).
- Cần đồng bộ dữ liệu hai chiều với hệ thống warehouse của chúng tôi.
- Cần phối hợp giữa nhiều team: đội của bạn, đội IT nội bộ và nhà cung cấp mạng.
- Cần audit logging chi tiết cho hồ sơ giám định.

Không cần thanh toán trong ứng dụng, và hiện tại chúng tôi chưa có kế hoạch chuyển dữ liệu lớn từ hệ thống cũ.

Trân trọng.`;

export async function mockScenarios(): Promise<Scenario[]> {
  await sleep(120);
  return [
    {
      id: "A",
      title: "Fintech payment + PCI",
      email_text: SCENARIO_A_EMAIL,
      notes: "Payments portal: PCI-DSS, real-time risk dashboard, GDPR data.",
    },
    {
      id: "B",
      title: "B2B SaaS multi-tenant + SSO",
      email_text: SCENARIO_B_EMAIL,
      notes: "Enterprise analytics: multi-tenancy, SSO, audit logging.",
    },
    {
      id: "C",
      title: "Field ops mobile — offline (VI)",
      email_text: SCENARIO_C_EMAIL,
      notes: "Vietnamese RFP: native mobile, offline-first, warehouse sync.",
    },
  ];
}

export async function mockLoadScenario(id: string): Promise<EstimateResponse> {
  const scenarios = await mockScenarios();
  const scenario =
    scenarios.find((s) => s.id.toLowerCase() === id.toLowerCase()) ?? scenarios[0];
  return mockEstimate(scenario.email_text);
}

function feats(names: string[]): Record<string, FeatureValue> {
  const record: Record<string, FeatureValue> = {};
  for (const feature of FEATURES) record[feature] = names.includes(feature) ? 1 : 0;
  return record;
}

function delta(actual: number, systemP50: number): number {
  return Number((((actual - systemP50) / systemP50) * 100).toFixed(1));
}

interface MockRowSeed {
  id: string;
  date: string;
  status: string;
  team: number;
  p50: number;
  p10?: number;
  p90?: number;
  actual?: number;
  featureNames: string[];
}

const ROW_SEEDS: MockRowSeed[] = [
  { id: "P047", date: "2026-05-02", status: "done", team: 34, p50: 41, actual: 44, featureNames: ["payment_gateway", "third_party_api", "pci_dss"] },
  { id: "P048", date: "2026-05-15", status: "done", team: 22, p50: 26, actual: 19, featureNames: ["audit_logging"] },
  { id: "P049", date: "2026-05-28", status: "done", team: 47, p50: 52, actual: 58, featureNames: ["data_migration", "legacy_tech_stack", "cross_team_coordination"] },
  { id: "P050", date: "2026-06-03", status: "done", team: 16, p50: 28, actual: 28, featureNames: ["realtime_ui", "third_party_api"] },
  { id: "P051", date: "2026-06-21", status: "done", team: 36, p50: 49, actual: 58, featureNames: ["multi_tenancy", "identity_provider", "audit_logging", "privacy_compliance"] },
  { id: "P052", date: "2026-06-28", status: "done", team: 29, p50: 39, actual: 46, featureNames: ["mobile_app", "offline_mode", "external_data_sync"] },
  { id: "P053", date: "2026-07-14", status: "in_progress", team: 71, p50: 63, p10: 46, p90: 88, featureNames: ["payment_gateway", "pci_dss", "third_party_api", "audit_logging", "multi_currency"] },
  { id: "P054", date: "2026-07-27", status: "in_progress", team: 53, p50: 57, p10: 40, p90: 79, featureNames: ["data_migration", "multi_tenancy", "audit_logging"] },
  { id: "P055", date: "2026-08-12", status: "in_progress", team: 46, p50: 41, p10: 30, p90: 57, featureNames: ["realtime_ui", "external_data_sync"] },
  { id: "P056", date: "2026-08-20", status: "in_progress", team: 40, p50: 44, p10: 31, p90: 61, featureNames: ["identity_provider", "privacy_compliance", "cross_team_coordination"] },
  { id: "P057", date: "2026-09-09", status: "in_progress", team: 32, p50: 35, p10: 25, p90: 49, featureNames: ["mobile_app", "offline_mode"] },
  { id: "P058", date: "2026-09-09", status: "pending", team: 97, p50: 88, p10: 62, p90: 123, featureNames: ["data_migration", "legacy_tech_stack", "multi_tenancy", "audit_logging"] },
  { id: "P059", date: "2026-10-03", status: "pending", team: 23, p50: 26, p10: 18, p90: 37, featureNames: ["third_party_api"] },
  { id: "P060", date: "2026-10-10", status: "pending", team: 60, p50: 55, p10: 39, p90: 76, featureNames: ["payment_gateway", "multi_currency", "privacy_compliance"] },
];

export async function mockProjects(): Promise<ProjectRow[]> {
  await sleep(150);
  return ROW_SEEDS.map((seed) => ({
    project_id: seed.id,
    date: seed.date,
    status: seed.status,
    team_estimate: seed.team,
    system_p50: seed.p50,
    system_p10: seed.p10 ?? Math.round(seed.p50 * 0.68),
    system_p90: seed.p90 ?? Math.round(seed.p50 * 1.4),
    actual_days: seed.actual ?? null,
    delta_pct: seed.actual ? delta(seed.actual, seed.p50) : null,
    features: feats(seed.featureNames),
  }));
}

export async function mockSubmitActual(
  projectId: string,
  actualDays: number
): Promise<ActualUpdateResponse> {
  await sleep(350);
  const rows = await mockProjects();
  const row = rows.find((r) => r.project_id === projectId) ?? rows[0];
  const systemP50 = row.system_p50 ?? 40;
  const updated: ProjectRow = {
    ...row,
    actual_days: actualDays,
    status: "done",
    delta_pct: delta(actualDays, systemP50),
  };
  const touched = FEATURES.filter((f) => row.features[f] === 1).slice(0, 3);
  const names = touched.length > 0 ? touched : ["third_party_api", "data_migration", "audit_logging"];
  const updates = names.map((feature, index) => {
    const current =
      MOCK_COEFFICIENTS.find((c) => c.feature === feature)?.multiplier ?? 1.2;
    return {
      feature,
      old: Number(current.toFixed(2)),
      new: Number((current * (actualDays > systemP50 ? 1.04 : 0.97)).toFixed(2)) + index * 0.001,
      sample_count: 26 + index * 7,
    };
  });
  const response: ActualUpdateResponse = {
    project: updated,
    coefficient_updates: updates,
    accuracy: {
      mae_before: 9.8,
      mae_after: actualDays > systemP50 ? 9.3 : 9.5,
      coverage_pct: 79.7,
    },
  };
  if (actualDays > 1000) {
    response.warning = "Giá trị bất thường, vui lòng kiểm tra lại";
  }
  return response;
}

export async function mockReplay(): Promise<ReplayResponse> {
  await sleep(1400); // replay is a real computation on the backend; keep the demo honest
  const steps: ReplayStep[] = [];
  for (let i = 11; i <= 52; i++) {
    const p50 = Math.round(17 + i * 0.75 + 6 * Math.sin(i / 2.3) + 8);
    const p10 = Math.round(p50 * 0.66);
    const p90 = Math.round(p50 * 1.36);
    const maeSystem = Number(
      (13.4 - (4.6 * (i - 11)) / 41 + 1.3 * Math.sin(i / 3.1)).toFixed(2)
    );
    const maeTeam = Number((14.7 + 0.9 * Math.sin(i / 5)).toFixed(2));
    const maeLlm = Number((13.1 + 1.6 * Math.sin(i / 4.3 + 1)).toFixed(2));
    const residual = Number((maeSystem * Math.cos(i * 0.9)).toFixed(1));
    const actual = Math.max(6, Math.round(p50 + residual));
    steps.push({
      i,
      project_id: `P${String(i).padStart(3, "0")}`,
      p10,
      p50,
      p90,
      actual,
      mae_system: maeSystem,
      mae_team: maeTeam,
      mae_llm_only: maeLlm,
      in_interval: actual >= p10 && actual <= p90,
    });
  }
  const inBand = steps.filter((s) => s.in_interval).length;
  return {
    steps,
    summary: {
      mae_system: 9.2,
      mae_team: 14.7,
      mae_llm_only: 13.1,
      coverage_pct: Number(((inBand / steps.length) * 100).toFixed(1)),
      llm_only_mode: "simulated",
      n_steps: steps.length,
    },
  };
}

export async function mockAb(emailText: string, n: number): Promise<ABResponse> {
  await sleep(900);
  const base = mockEstimate(emailText).estimate.p50;
  const offsets = [-0.09, 0.05, -0.03, 0.11, -0.06, 0.02, 0.08, -0.12, 0.04, -0.01];
  const values = Array.from({ length: Math.min(n, offsets.length) }, (_, index) =>
    Math.max(5, Math.round(base * (1 + offsets[index])))
  );
  const mean = Number((values.reduce((a, b) => a + b, 0) / values.length).toFixed(1));
  const variance =
    values.reduce((acc, v) => acc + (v - mean) ** 2, 0) / Math.max(1, values.length - 1);

  // "LLM + company history" strawman (contract v0.2): a slightly-high, low-
  // variance spread — history nudges a raw LLM up and stabilises it a bit.
  const historyOffsets = [0.11, 0.04, 0.08];
  const historyValues = historyOffsets.map((offset) =>
    Math.max(5, Math.round(base * (1 + offset)))
  );
  const historyMean = Number(
    (historyValues.reduce((a, b) => a + b, 0) / historyValues.length).toFixed(1)
  );
  const historyVariance =
    historyValues.reduce((acc, v) => acc + (v - historyMean) ** 2, 0) /
    Math.max(1, historyValues.length - 1);

  return {
    mode: "simulated",
    values,
    mean,
    std: Number(Math.sqrt(variance).toFixed(2)),
    min: Math.min(...values),
    max: Math.max(...values),
    system_estimate: base,
    delta_pct: Number((((mean - base) / base) * 100).toFixed(1)),
    note:
      "Simulated: offline stub provider — run-to-run variance is emulated with seeded noise (no API key configured).",
    n: values.length,
    errors: 0,
    provider: "stub",
    baseline_history: {
      values: historyValues,
      mean: historyMean,
      std: Number(Math.sqrt(historyVariance).toFixed(2)),
      n: historyValues.length,
      mode: "simulated",
      min: Math.min(...historyValues),
      max: Math.max(...historyValues),
      errors: 0,
      note:
        "SIMULATED LLM-with-history baseline: stub provider, the history block is emulated offline.",
    },
  };
}

export async function mockImport(file: File): Promise<ImportResponse> {
  await sleep(600);
  return {
    imported: 12,
    skipped: 1,
    errors: [`row 7: actual_days invalid ('abc') — skipped "${file.name}" row`],
  };
}
