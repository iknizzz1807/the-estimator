"use client";

import {
  Bar,
  BarChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip as ChartTooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { EstimateRange } from "@/lib/types";
import { fmtInt } from "@/lib/format";
import { GLOSSARY, Term } from "./Tooltip";

export function ModeBadge({ mode }: { mode: string }) {
  const calibrated = mode === "calibrated";
  return (
    <span
      className={`chip ${calibrated ? "chip-ok" : "chip-unknown"}`}
      title={GLOSSARY.mode}
    >
      {calibrated ? "● calibrated" : "◐ cold start"}
    </span>
  );
}

interface RangeRow {
  name: string;
  range: [number, number];
}

function BandTooltip({
  active,
  payload,
  estimate,
}: {
  active?: boolean;
  payload?: Array<{ payload?: RangeRow }>;
  estimate: EstimateRange;
}) {
  if (!active || !payload?.length) return null;
  return (
    <div className="panel-2 px-2.5 py-1.5 text-[11px] shadow-lg">
      <div className="text-[var(--dim)]">80% prediction interval</div>
      <div className="num text-[var(--cyan)]">
        P10 {fmtInt(estimate.p10)} → P90 {fmtInt(estimate.p90)} days
      </div>
      <div className="num text-[var(--lime)]">
        P50 {fmtInt(estimate.p50)} days
      </div>
    </div>
  );
}

function MedianCursorLabel() {
  return <span className="text-[10px] text-[var(--lime)]">P50</span>;
}

/**
 * ● P10/P50/P90 range visualization: an 80% interval band with the median
 * marked — the headline answer of the product (spec §6.1).
 */
export function EstimateChart({
  estimate,
  projectsCount,
  similarCount,
  topScore,
}: {
  estimate: EstimateRange;
  projectsCount: number | null;
  similarCount: number;
  topScore: number | null;
}) {
  const { p10, p50, p90, unit, mode } = estimate;
  const domainMax = Math.ceil(p90 * 1.15);
  const data: RangeRow[] = [{ name: "Effort", range: [p10, p90] }];

  const basis =
    mode === "calibrated" && projectsCount
      ? `based on ${projectsCount} historical projects`
      : "based on documented industry baselines — wider interval until history accumulates";

  return (
    <div>
      <div className="mb-1 flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <span className="num text-4xl font-semibold text-[var(--text)]">
          {fmtInt(p50)}
        </span>
        <span className="text-sm text-[var(--dim)]">{unit} (P50)</span>
        <ModeBadge mode={mode} />
      </div>
      <p className="text-xs leading-5 text-[var(--dim)]">
        P50 = {fmtInt(p50)} {unit}, {basis}
        {similarCount > 0 ? ` · ${similarCount} similar projects` : ""}
        {topScore !== null ? ` · top match score ${topScore.toFixed(2)}` : ""}.
      </p>

      <div className="mt-3">
        <ResponsiveContainer width="100%" height={92}>
          <BarChart
            layout="vertical"
            data={data}
            margin={{ top: 8, right: 24, bottom: 4, left: 0 }}
          >
            <XAxis
              type="number"
              domain={[0, domainMax]}
              tick={{ fill: "var(--faint)", fontSize: 10 }}
              tickFormatter={(value: number) => fmtInt(value)}
              stroke="var(--border)"
            />
            <YAxis type="category" dataKey="name" hide />
            <ChartTooltip
              cursor={{ fill: "rgba(34,211,238,0.05)" }}
              content={<BandTooltip estimate={estimate} />}
            />
            <Bar
              dataKey="range"
              fill="rgba(34,211,238,0.28)"
              stroke="rgba(34,211,238,0.7)"
              barSize={30}
              radius={6}
            />
            <ReferenceLine
              x={p50}
              stroke="var(--lime)"
              strokeWidth={2}
              label={<MedianCursorLabel />}
            />
          </BarChart>
        </ResponsiveContainer>
        <div className="flex justify-between text-[10px] text-[var(--faint)]">
          <span>0 {unit}</span>
          <span className="num">P90 {fmtInt(p90)} {unit}</span>
        </div>
      </div>

      <div className="mt-3 grid grid-cols-3 gap-2">
        {(
          [
            ["P10", p10, GLOSSARY.p10, "text-[var(--cyan)]"],
            ["P50", p50, GLOSSARY.p50, "text-[var(--lime)]"],
            ["P90", p90, GLOSSARY.p90, "text-[var(--amber)]"],
          ] as const
        ).map(([label, value, tip, color]) => (
          <div key={label} className="panel-2 px-3 py-2">
            <div className="text-[10.5px] uppercase tracking-[0.1em] text-[var(--dim)]">
              <Term term={label} tip={tip}>
                {label}
              </Term>
            </div>
            <div className={`num mt-0.5 text-xl font-semibold ${color}`}>
              {fmtInt(value)}
              <span className="ml-1 text-[11px] font-normal text-[var(--dim)]">
                {unit}
              </span>
            </div>
          </div>
        ))}
      </div>
      <p className="mt-2 text-[11px] text-[var(--faint)]">
        <Term term="Conformal prediction" tip={GLOSSARY.conformal}>
          80% interval
        </Term>{" "}
        — built from out-of-fold residuals; expect ~1 in 5 projects to fall
        outside. Range, not a promise.
      </p>
    </div>
  );
}
