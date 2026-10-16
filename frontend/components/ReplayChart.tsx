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
    <div className="panel-2 px-2.5 py-2 text-[11px] shadow-lg">
      <div className="num text-[var(--text)]">
        step {row.i} · {row.project_id}
      </div>
      <div className="num mt-1 text-[var(--cyan)]">
        system MAE {fmtNum(row.system, 2)}
      </div>
      <div className="num text-[var(--dim)]">team MAE {fmtNum(row.team, 2)}</div>
      <div className="num text-[var(--amber)]">LLM-only {fmtNum(row.llm, 2)}</div>
    </div>
  );
}

/**
 * Walk-forward MAE over project index: system (cyan solid), team (gray),
 * LLM-only (amber dashed). The LLM-only line is flagged simulated when the
 * backend says so (stub provider, docs/DECISIONS.md D2).
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
          <CartesianGrid stroke="var(--border)" strokeDasharray="3 6" />
          <XAxis
            dataKey="i"
            tick={{ fill: "var(--faint)", fontSize: 10 }}
            stroke="var(--border)"
            label={{
              value: "project index (train on 1..i-1, predict i)",
              position: "insideBottom",
              offset: -2,
              fill: "var(--faint)",
              fontSize: 10,
            }}
          />
          <YAxis
            tick={{ fill: "var(--faint)", fontSize: 10 }}
            stroke="var(--border)"
            domain={[0, "auto"]}
            tickFormatter={(value: number) => fmtInt(value)}
          />
          <ChartTooltip content={<ReplayTooltip />} />
          <ReferenceLine
            y={10}
            stroke="var(--amber)"
            strokeDasharray="4 4"
            label={{
              value: "target MAE < 10 d",
              position: "insideTopRight",
              fill: "var(--amber)",
              fontSize: 10,
            }}
          />
          <Legend
            wrapperStyle={{ fontSize: 11, color: "var(--dim)" }}
            formatter={(value: string) => <span className="text-[var(--dim)]">{value}</span>}
          />
          <Line
            type="monotone"
            dataKey="system"
            name="System (Ridge + conformal)"
            stroke="var(--cyan)"
            strokeWidth={2}
            dot={false}
          />
          <Line
            type="monotone"
            dataKey="team"
            name="Team estimate"
            stroke="#64748b"
            strokeWidth={1.6}
            dot={false}
          />
          <Line
            type="monotone"
            dataKey="llm"
            name={`LLM-only${summary.llm_only_mode === "simulated" ? " (simulated)" : ""}`}
            stroke="var(--amber)"
            strokeWidth={1.6}
            strokeDasharray="6 4"
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
