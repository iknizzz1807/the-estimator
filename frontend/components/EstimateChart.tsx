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
      className={`inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-[11px] font-medium tracking-wide ${
        calibrated
          ? "border-[rgba(39,166,68,0.3)] bg-[rgba(39,166,68,0.1)] text-[#27a644]"
          : "border-[rgba(245,158,11,0.3)] bg-[rgba(245,158,11,0.1)] text-[#f59e0b]"
      }`}
      title={GLOSSARY.mode}
    >
      <span
        className={`h-1.5 w-1.5 rounded-full ${
          calibrated ? "bg-[#27a644]" : "bg-[#f59e0b]"
        }`}
      />
      {calibrated ? "Calibrated" : "Cold start"}
    </span>
  );
}

/**
 * Interval method badge (contract v0.2): "mc" is amber because a Monte-Carlo
 * interval is honestly widened by the remaining unknown features; "point"
 * means the vector was fully known. Renders nothing on v0.1 payloads.
 */
export function MethodBadge({
  method,
  unknownCount,
}: {
  method?: string;
  unknownCount: number;
}) {
  if (!method) return null;
  if (method === "mc") {
    return (
      <span
        className="inline-flex items-center gap-1.5 rounded-full border border-[rgba(245,158,11,0.3)] bg-[rgba(245,158,11,0.1)] px-2 py-0.5 text-[11px] font-medium tracking-wide text-[#f59e0b]"
        title={GLOSSARY.mc}
        aria-label={`Monte Carlo interval, widened by ${unknownCount} unknown features`}
      >
        <span className="h-1.5 w-1.5 rounded-full bg-[#f59e0b]" />
        MC: +{unknownCount} unknown{unknownCount === 1 ? "" : "s"}
      </span>
    );
  }
  return (
    <span
      className="inline-flex items-center gap-1.5 rounded-full border border-[#23252a] bg-[#141516] px-2 py-0.5 text-[11px] font-medium tracking-wide text-[#8a8f98]"
      title={GLOSSARY.point}
      aria-label="Point estimate, all features known"
    >
      <span className="h-1.5 w-1.5 rounded-full bg-[#62666d]" />
      Point
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
    <div className="rounded-lg border border-[#23252a] bg-[#0f1011] p-3 text-xs shadow-2xl backdrop-blur-md">
      <div className="text-[11px] uppercase tracking-wider text-[#8a8f98]">
        80% Prediction Interval
      </div>
      <div className="mt-1 flex items-baseline gap-2 font-mono tabular-nums">
        <span className="text-[#8a8f98]">P10 {fmtInt(estimate.p10)}d</span>
        <span className="text-[#62666d]">→</span>
        <span className="text-sm font-semibold text-[#5e6ad2]">
          P50 {fmtInt(estimate.p50)}d
        </span>
        <span className="text-[#62666d]">→</span>
        <span className="text-[#f7f8f8]">P90 {fmtInt(estimate.p90)}d</span>
      </div>
    </div>
  );
}

function MedianIndicatorLabel({ x, y }: { x?: number; y?: number }) {
  if (x === undefined || y === undefined) return null;
  return (
    <g transform={`translate(${x}, ${y - 12})`}>
      <rect
        x="-16"
        y="-12"
        width="32"
        height="16"
        rx="3"
        fill="#5e6ad2"
      />
      <text
        x="0"
        y="0"
        fill="#ffffff"
        fontSize="9"
        fontWeight="600"
        fontFamily="sans-serif"
        textAnchor="middle"
        dominantBaseline="middle"
      >
        P50
      </text>
    </g>
  );
}

/**
 * P10/P50/P90 range visualization: an 80% interval band with the median
 * marked in Linear lavender (#5e6ad2) — the headline answer of the product.
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
  const domainMax = Math.ceil(p90 * 1.18);
  const data: RangeRow[] = [{ name: "Effort", range: [p10, p90] }];

  const basis =
    mode === "calibrated" && projectsCount
      ? `calibrated on ${projectsCount} historical projects`
      : "documented industry baselines (wider interval until history accumulates)";

  return (
    <div className="space-y-4">
      <div>
        <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
          <span className="font-mono text-4xl font-semibold tracking-tight text-[#f7f8f8]">
            {fmtInt(p50)}
          </span>
          <span className="text-sm font-medium text-[#8a8f98]">{unit}</span>
          <span className="rounded-full border border-[rgba(94,106,210,0.3)] bg-[rgba(94,106,210,0.12)] px-2 py-0.5 font-mono text-[11px] font-semibold text-[#828fff]">
            P50 Median
          </span>
          <ModeBadge mode={mode} />
        </div>

        <p className="mt-1 text-xs leading-relaxed text-[#8a8f98]">
          Effort median is <span className="font-mono text-[#f7f8f8]">{fmtInt(p50)} {unit}</span>, {basis}
          {similarCount > 0 ? ` · ${similarCount} similar projects` : ""}
          {topScore !== null ? ` · top match score ${topScore.toFixed(2)}` : ""}.
        </p>
      </div>

      {/* Sleek Recharts Range Bar */}
      <div className="rounded-lg border border-[#23252a] bg-[#0f1011] p-3.5">
        <div className="mb-2 flex items-center justify-between text-[11px] text-[#8a8f98]">
          <span className="uppercase tracking-wider">Uncertainty Band (80% Range)</span>
          <span className="font-mono tabular-nums text-[#62666d]">
            Span: {fmtInt(p90 - p10)} {unit}
          </span>
        </div>

        <div className="h-20 w-full">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart
              layout="vertical"
              data={data}
              margin={{ top: 14, right: 24, bottom: 0, left: 4 }}
            >
              <XAxis
                type="number"
                domain={[0, domainMax]}
                tick={{ fill: "#62666d", fontSize: 10, fontFamily: "ui-monospace" }}
                tickFormatter={(value: number) => fmtInt(value)}
                stroke="#23252a"
                tickLine={false}
              />
              <YAxis type="category" dataKey="name" hide />
              <ChartTooltip
                cursor={{ fill: "rgba(94,106,210,0.04)" }}
                content={<BandTooltip estimate={estimate} />}
              />
              <Bar
                dataKey="range"
                fill="rgba(94, 106, 210, 0.18)"
                stroke="#5e6ad2"
                strokeWidth={1}
                barSize={24}
                radius={6}
              />
              <ReferenceLine
                x={p50}
                stroke="#5e6ad2"
                strokeWidth={2}
                label={<MedianIndicatorLabel />}
              />
            </BarChart>
          </ResponsiveContainer>
        </div>

        <div className="mt-1 flex justify-between border-t border-[#23252a]/60 pt-2 text-[10.5px] text-[#62666d]">
          <span className="font-mono tabular-nums">0 {unit}</span>
          <span className="font-mono tabular-nums text-[#8a8f98]">
            P90: {fmtInt(p90)} {unit}
          </span>
        </div>
      </div>

      {/* High-precision Tabular Numbers Stat Cards */}
      <div className="grid grid-cols-3 gap-2.5">
        <div className="group rounded-lg border border-[#23252a] bg-[#0f1011] p-3 transition-colors hover:border-[#34343a] hover:bg-[#141516]">
          <div className="text-[10px] font-medium uppercase tracking-[0.1em] text-[#8a8f98]">
            <Term term="P10" tip={GLOSSARY.p10}>
              P10 Optimistic
            </Term>
          </div>
          <div className="mt-1 flex items-baseline gap-1 font-mono text-2xl font-semibold tabular-nums text-[#8a8f98] group-hover:text-[#d0d6e0]">
            {fmtInt(p10)}
            <span className="text-xs font-normal text-[#62666d]">{unit}</span>
          </div>
          <p className="mt-1 text-[10px] leading-tight text-[#62666d]">
            ~10% faster
          </p>
        </div>

        <div className="group rounded-lg border border-[#5e6ad2]/50 bg-[#141516] p-3 shadow-[0_0_20px_rgba(94,106,210,0.08)] transition-colors hover:border-[#5e6ad2]">
          <div className="text-[10px] font-medium uppercase tracking-[0.1em] text-[#828fff]">
            <Term term="P50" tip={GLOSSARY.p50}>
              P50 Median
            </Term>
          </div>
          <div className="mt-1 flex items-baseline gap-1 font-mono text-2xl font-bold tabular-nums text-[#5e6ad2] group-hover:text-[#828fff]">
            {fmtInt(p50)}
            <span className="text-xs font-normal text-[#828fff]/70">{unit}</span>
          </div>
          <p className="mt-1 text-[10px] leading-tight text-[#8a8f98]">
            Calibrated target
          </p>
        </div>

        <div className="group rounded-lg border border-[#23252a] bg-[#0f1011] p-3 transition-colors hover:border-[#34343a] hover:bg-[#141516]">
          <div className="text-[10px] font-medium uppercase tracking-[0.1em] text-[#8a8f98]">
            <Term term="P90" tip={GLOSSARY.p90}>
              P90 Conservative
            </Term>
          </div>
          <div className="mt-1 flex items-baseline gap-1 font-mono text-2xl font-semibold tabular-nums text-[#f7f8f8]">
            {fmtInt(p90)}
            <span className="text-xs font-normal text-[#62666d]">{unit}</span>
          </div>
          <p className="mt-1 text-[10px] leading-tight text-[#62666d]">
            Upper bound risk
          </p>
        </div>
      </div>

      <p className="text-[11px] leading-relaxed text-[#62666d]">
        <Term term="Conformal prediction" tip={GLOSSARY.conformal}>
          <span className="text-[#8a8f98] underline decoration-dotted decoration-[#62666d] underline-offset-2">
            80% conformal interval
          </span>
        </Term>{" "}
        calculated from out-of-fold residuals (~1 in 5 projects could fall outside). Range, not a promise.
      </p>
    </div>
  );
}
