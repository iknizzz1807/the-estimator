"use client";

import type { EstimateResponse } from "@/lib/types";
import { featureLabel } from "@/lib/features";
import { fmtInt } from "@/lib/format";

/**
 * Print-only proposal view (window.print()): range, assumptions, questions
 * and the "demo data, range not a promise" disclaimer. Light theme via the
 * print stylesheet in globals.css.
 */
export function ProposalPrintView({
  estimate,
  emailExcerpt,
  provider,
  projectsCount,
  generatedAt,
}: {
  estimate: EstimateResponse;
  emailExcerpt: string;
  provider: string;
  projectsCount: number | null;
  generatedAt: string;
}) {
  const { estimate: range, questions, similar_projects, coefficients } = estimate;
  const topCoefficients = [...coefficients]
    .sort((a, b) => b.multiplier - a.multiplier)
    .slice(0, 3);

  return (
    <div className="print-only print-proposal">
      <h1>
        The Estimator — effort estimate ({estimate.project_id ?? "—"})
      </h1>
      <p>
        Generated {generatedAt} · extraction provider: {provider} · demo build
        with synthetic data.
      </p>

      <h2>Estimated effort</h2>
      <table>
        <tbody>
          <tr>
            <th>P10 (optimistic)</th>
            <th>P50 (median)</th>
            <th>P90 (conservative)</th>
            <th>Mode</th>
          </tr>
          <tr>
            <td>
              {fmtInt(range.p10)} {range.unit}
            </td>
            <td>
              {fmtInt(range.p50)} {range.unit}
            </td>
            <td>
              {fmtInt(range.p90)} {range.unit}
            </td>
            <td>{range.mode === "calibrated" ? "calibrated" : "cold start"}</td>
          </tr>
        </tbody>
      </table>
      <p>
        80% prediction interval (conformal). P50 based on{" "}
        {range.mode === "calibrated" && projectsCount
          ? `${projectsCount} historical projects`
          : "documented industry baselines (no/too little history)"}
        .
      </p>

      <h2>Request excerpt</h2>
      <p>{emailExcerpt}</p>

      <h2>Assumptions — top learned multipliers</h2>
      <table>
        <thead>
          <tr>
            <th>Feature</th>
            <th>Multiplier</th>
            <th>Samples</th>
          </tr>
        </thead>
        <tbody>
          {topCoefficients.map((coefficient) => (
            <tr key={coefficient.feature}>
              <td>{featureLabel(coefficient.feature)}</td>
              <td>×{coefficient.multiplier.toFixed(2)}</td>
              <td>{coefficient.sample_count}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <h2>Comparable past projects</h2>
      <table>
        <thead>
          <tr>
            <th>Project</th>
            <th>Description</th>
            <th>Similarity</th>
            <th>Actual days</th>
          </tr>
        </thead>
        <tbody>
          {similar_projects.map((project) => (
            <tr key={project.project_id}>
              <td>{project.project_id}</td>
              <td>{project.title_hint}</td>
              <td>{project.score.toFixed(2)}</td>
              <td>{fmtInt(project.actual_days)}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <h2>Open questions to confirm scope ({questions.length})</h2>
      <ol>
        {questions.map((question) => (
          <li key={question.feature}>
            {question.question_en} (impact ≈ {fmtInt(question.impact_days)} days)
          </li>
        ))}
      </ol>

      <p className="disclaimer">
        Synthetic demo data — the interval above is a range, not a promise.
        Coverage target 75–85% on held-out projects; feature extraction can err
        and is evidence-linked for review.
      </p>
    </div>
  );
}
