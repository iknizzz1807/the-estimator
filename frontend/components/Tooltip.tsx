import type { ReactNode } from "react";

/**
 * Glossary tooltip for technical terms (P10/P50/P90, conformal prediction,
 * Value of Information, MAE, coverage %). Hover or keyboard focus reveals
 * the definition; title fallback keeps it accessible everywhere.
 */
export function Term({ term, tip, children }: { term: string; tip: string; children?: ReactNode }) {
  return (
    <span className="term" tabIndex={0} title={`${term} — ${tip}`} aria-label={`${term}: ${tip}`}>
      {children ?? term}
      <span className="term-tip" role="tooltip">
        <strong className="text-[var(--primary)]">{term}</strong> — {tip}
      </span>
    </span>
  );
}

export const GLOSSARY = {
  p10: "10th percentile of the predicted effort — the optimistic end. Roughly 10% of comparable projects finished faster.",
  p50: "Median predicted effort — half of comparable projects finished faster, half slower. A headline number, not a promise.",
  p90: "90th percentile — the conservative end. Plan capacity so ~1 in 10 projects could exceed this.",
  conformal:
    "Conformal prediction: a distribution-free method that turns out-of-fold model residuals into the [P10, P90] interval, targeting ~80% coverage on held-out projects.",
  voi: "Value of Information: the expected estimate shift (in days) from answering a question. Questions are ranked by impact.",
  mae: "Mean Absolute Error: the average gap in days between estimates and actuals across replay steps. Lower is better.",
  coverage:
    "Coverage: share of replayed projects whose actual days fell inside [P10, P90]. The target band is 75–85%.",
  mode: "calibrated = trained on company history; cold_start = documented industry baselines with a wider interval (no/too little history).",
  provider:
    "Extraction provider from /api/health. stub is a deterministic offline rule-based extractor — results are flagged so nobody mistakes it for a real LLM.",
  delta: "Δ%: (actual − system P50) ÷ system P50. ≤10% neutral, 10–25% review, >25% critical miss.",
  impact:
    "Estimated swing in the P50 if the feature turns out present vs absent — the bigger the swing, the more valuable the answer.",
  mc: "Monte Carlo interval: every feature still unknown is sampled from its historical prevalence instead of being assumed absent, so the interval is honestly wider — more unknowns ⇒ wider range. Answering the ranked questions resolves unknowns and narrows the relative uncertainty (a Yes that adds scope can widen the range).",
  point:
    "Point estimate: the feature vector is fully known (or the model runs cold-start), so no Monte-Carlo widening is applied.",
  overBudget:
    "P(days) over budget: the chance the actual duration exceeds the budget under this package's predictive distribution — a lognormal fit through P10/P50/P90. ≤25% = comfortable, ≤50% = risky, >50% = likely over budget.",
} as const;
