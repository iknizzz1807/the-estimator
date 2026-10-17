"use client";

import type { Coefficient, EstimateRange, Finding } from "@/lib/types";
import { featureLabel } from "@/lib/features";
import { fmtInt } from "@/lib/format";
import { Term } from "./Tooltip";

const SEGMENT_COLORS = [
  "#5e6ad2", // Linear lavender
  "#828fff", // lavender hover
  "#7a7fad", // brand secure
  "#27a644", // semantic success
  "#d0d6e0", // ink-muted
];
const BACKLOG_COLOR = "#34343a";
const BASE_COLOR = "#191a1b";

const APPROX_TIP =
  "Approximation, not the model's internals: the learned model is multiplicative, so we decompose P50 in reverse — each bar is the drop in P50 if that capability were removed (remaining estimate × (1 − 1/multiplier)), in descending multiplier order. Order-dependent and illustrative only.";

/**
 * P50 contribution bar: decomposes the median into a base plus the present
 * features' learned multipliers. A documented approximation (see tooltip) —
 * the point is to show *which capabilities drive the number*, not to expose
 * exact model arithmetic.
 */
export function ContributionBar({
  estimate,
  coefficients,
  findings,
}: {
  estimate: EstimateRange;
  coefficients: Coefficient[];
  findings: Finding[];
}) {
  if (!estimate.p50 || estimate.p50 <= 0) return null;
  const multiplier = new Map(
    coefficients.map((coefficient) => [
      coefficient.feature,
      coefficient.multiplier,
    ])
  );
  const present = findings
    .filter((finding) => finding.value === 1)
    .map((finding) => ({
      feature: finding.name,
      mult: multiplier.get(finding.name) ?? 1,
    }))
    .filter((item) => item.mult > 1.001)
    .sort((a, b) => b.mult - a.mult);

  if (present.length === 0) return null;

  let remaining = estimate.p50;
  const contributions = present.map((item) => {
    const days = remaining * (1 - 1 / item.mult);
    remaining -= days;
    return { feature: item.feature, days };
  });
  const base = remaining;
  const shown = contributions.slice(0, 5);
  const restDays = contributions
    .slice(5)
    .reduce((acc, item) => acc + item.days, 0);

  const segments: Array<{
    label: string;
    days: number;
    color: string;
    isBase?: boolean;
  }> = [
    { label: "Base", days: base, color: BASE_COLOR, isBase: true },
    ...shown.map((item, index) => ({
      label: featureLabel(item.feature),
      days: item.days,
      color: SEGMENT_COLORS[index % SEGMENT_COLORS.length],
    })),
  ];
  if (restDays > 0) {
    segments.push({
      label: `other (${present.length - shown.length})`,
      days: restDays,
      color: BACKLOG_COLOR,
    });
  }

  return (
    <div className="mb-3">
      <div className="mb-1 flex flex-wrap items-center justify-between gap-2">
        <span className="text-[11px] uppercase tracking-[0.1em] text-[var(--dim)]">
          <Term term="P50 contribution" tip={APPROX_TIP}>
            What drives the P50
          </Term>
        </span>
        <span className="num text-[11px] text-[var(--faint)]">
          {fmtInt(estimate.p50)} {estimate.unit} total
        </span>
      </div>
      <div
        className="flex h-4 w-full overflow-hidden rounded-full border border-[var(--border)]"
        title={APPROX_TIP}
      >
        {segments.map((segment) => (
          <div
            key={segment.label}
            style={{
              width: `${Math.max(0, (segment.days / estimate.p50) * 100)}%`,
              background: segment.color,
            }}
            title={
              segment.isBase
                ? `Base: ${fmtInt(segment.days)} ${estimate.unit} before feature multipliers — this is the floor`
                : `${segment.label}: ≈ −${fmtInt(segment.days)} ${estimate.unit} if removed`
            }
          />
        ))}
      </div>
      <div className="mt-1.5 flex flex-wrap gap-x-3 gap-y-1 text-[10.5px] text-[var(--faint)]">
        {segments.map((segment) => (
          <span key={segment.label} className="flex items-center gap-1">
            <span
              className="inline-block h-2 w-2 rounded-sm"
              style={{ background: segment.color }}
            />
            {segment.label}{" "}
            <span className="num text-[var(--dim)]">
              {segment.isBase ? "" : "−"}
              {fmtInt(segment.days)} {estimate.unit}
            </span>
          </span>
        ))}
      </div>
    </div>
  );
}
