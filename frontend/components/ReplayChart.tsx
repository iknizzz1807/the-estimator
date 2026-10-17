"use client";

import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip as ChartTooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { ReplayStep, ReplaySummary } from "@/lib/types";
import { fmtInt, fmtNum } from "@/lib/format";

interface Row {
  i: number;
  project_id: string;
  system: number;
  team: number;
  llm: number;
}

function ReplayTooltip({
  active,
  payload,
}: {
  active?: boolean;
  payload?: Array<{ payload?: Row }>;
}) {
  const row = payload?.[0]?.payload;
  if (!active || !row) return null;
  return (
    <div className="rounded-lg border border-[var(--hairline-strong)] bg-[var(--surface-2)] px-3 py-2 text-[11px] shadow-[0_12px_32px_rgba(0,0,0,0.8)]">
      <div className="num font-medium text-[var(--ink)]">
        step {row.i} · {row.project_id}
      </div>
      <div className="num mt-1 font-semibold text-[var(--primary)]">
        system MAE {fmtNum(row.system, 2)}
      </div>
      <div className="num text-[var(--ink-subtle)]">team MAE {fmtNum(row.team, 2)}</div>
      <div className="num text-[var(--warning)]">LLM-only {fmtNum(row.llm, 2)}</div>
    </div>
  );
}

/**
 * Walk-forward MAE over project index: system (Linear lavender solid), team (gray),
 * LLM-only (amber dashed).
 */
export function ReplayChart({
  steps,
  summary,
}: {
  steps: ReplayStep[];
  summary: ReplaySummary;
}) {
  const hasPerStepLlm = steps.some(
    (step) => step.mae_llm_only !== null && step.mae_llm_only !== undefined
  );
  const data: Row[] = steps.map((step) => ({
    i: step.i,
    project_id: step.project_id,
    system: step.mae_system,
    team: step.mae_team,
    llm: step.mae_llm_only ?? summary.mae_llm_only,
  }));

  return (
    <div>
      <ResponsiveContainer width="100%" height={280}>
        <LineChart data={data} margin={{ top: 8, right: 16, bottom: 4, left: -12 }}>
          <CartesianGrid stroke="var(--hairline)" strokeDasharray="3 6" />
          <XAxis
            dataKey="i"
            tick={{ fill: "var(--ink-tertiary)", fontSize: 10 }}
            stroke="var(--hairline)"
            label={{
              value: "project index (train on 1..i-1, predict i)",
              position: "insideBottom",
              offset: -2,
              fill: "var(--ink-tertiary)",
              fontSize: 10,
            }}
          />
          <YAxis
            tick={{ fill: "var(--ink-tertiary)", fontSize: 10 }}
            stroke="var(--hairline)"
            domain={[0, "auto"]}
            tickFormatter={(value: number) => fmtInt(value)}
          />
          <ChartTooltip content={<ReplayTooltip />} />
          <ReferenceLine
            y={10}
            stroke="var(--success)"
            strokeDasharray="4 4"
            label={{
              value: "target MAE < 10 d",
              position: "insideTopRight",
              fill: "var(--success)",
              fontSize: 10,
            }}
          />
          <Legend
            wrapperStyle={{ fontSize: 11, color: "var(--ink-subtle)" }}
            formatter={(value: string) => <span className="text-[var(--ink-subtle)]">{value}</span>}
          />
          <Line
            type="monotone"
            dataKey="system"
            name="System (Ridge + conformal)"
            stroke="var(--primary)"
            strokeWidth={2}
            dot={false}
          />
          <Line
            type="monotone"
            dataKey="team"
            name="Team estimate"
            stroke="var(--ink-tertiary)"
            strokeWidth={1.5}
            dot={false}
          />
          <Line
            type="monotone"
            dataKey="llm"
            name={`LLM-only${summary.llm_only_mode === "simulated" ? " (simulated)" : ""}`}
            stroke="var(--warning)"
            strokeWidth={1.5}
            strokeDasharray="5 3"
            dot={false}
          />
        </LineChart>
      </ResponsiveContainer>
      <p className="mt-1 text-[11px] text-[var(--faint)]">
        MAE in days, lower is better. LLM-only line:{" "}
        {hasPerStepLlm
          ? "per-step values from the replay."
          : "flat summary value (backend reports no per-step LLM baseline)."}
        {summary.llm_only_mode === "simulated" && (
          <>
            {" "}
            <span className="chip chip-unknown">simulated (stub provider)</span>
          </>
        )}
      </p>
    </div>
  );
}
