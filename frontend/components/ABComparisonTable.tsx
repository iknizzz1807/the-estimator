"use client";

import {
  Bar,
  BarChart,
  ResponsiveContainer,
  Tooltip as ChartTooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { ABResponse } from "@/lib/types";
import { fmtNum, fmtPct } from "@/lib/format";
import { Term } from "./Tooltip";

/**
 * A/B comparison (spec §4.5): 10 LLM-only runs of the same email vs the
 * system estimate. The stub provider's variance is simulated — clearly
 * labelled so nobody mistakes it for a real LLM measurement.
 */
export function ABComparisonTable({ data }: { data: ABResponse }) {
  const bins = 5;
  const span = Math.max(1, data.max - data.min);
  const width = span / bins;
  const counts = Array.from({ length: bins }, () => 0);
  data.values.forEach((value) => {
    const index = Math.min(bins - 1, Math.max(0, Math.floor((value - data.min) / width)));
    counts[index] += 1;
  });
  const histogram = counts.map((count, index) => ({
    label: `${Math.round(data.min + index * width)}–${Math.round(data.min + (index + 1) * width)}`,
    count,
  }));

  const deltaClass =
    Math.abs(data.delta_pct) <= 5
      ? "text-[var(--text)]"
      : Math.abs(data.delta_pct) <= 15
        ? "text-[var(--orange)]"
        : "text-[var(--red)]";

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        {data.mode === "simulated" ? (
          <span className="chip chip-unknown" title="No API key configured — variance is emulated with seeded noise">
            simulated — no API key
          </span>
        ) : (
          <span className="chip chip-ok">real LLM runs</span>
        )}
        <span className="num text-[11px] text-[var(--faint)]">
          n = {data.values.length} runs
        </span>
      </div>

      <div className="grid gap-3 lg:grid-cols-2">
        <div>
          <table className="data-table">
            <thead>
              <tr>
                <th>Statistic</th>
                <th>LLM-only</th>
                <th>Context</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td>Mean</td>
                <td className="num text-[var(--amber)]">{fmtNum(data.mean, 1)} d</td>
                <td className="text-xs text-[var(--faint)]">
                  average of {data.values.length} single-number answers
                </td>
              </tr>
              <tr>
                <td>
                  <Term term="Std dev" tip="Spread of the LLM-only answers across runs — the system should be far more consistent than this.">
                    Std dev
                  </Term>
                </td>
                <td className="num text-[var(--amber)]">{fmtNum(data.std, 2)} d</td>
                <td className="text-xs text-[var(--faint)]">
                  run-to-run variance; lower is better
                </td>
              </tr>
              <tr>
                <td>Min / Max</td>
                <td className="num text-[var(--amber)]">
                  {fmtNum(data.min, 0)} / {fmtNum(data.max, 0)} d
                </td>
                <td className="text-xs text-[var(--faint)]">
                  spread of ±{fmtNum((data.max - data.min) / 2, 1)} days around the mean
                </td>
              </tr>
              <tr>
                <td>System estimate</td>
                <td className="num text-[var(--cyan)]">
                  {fmtNum(data.system_estimate, 0)} d (P50)
                </td>
                <td className="text-xs text-[var(--faint)]">
                  same email through the full pipeline — deterministic
                </td>
              </tr>
              <tr>
                <td>Δ mean vs system</td>
                <td className={`num ${deltaClass}`}>
                  {data.delta_pct > 0 ? "+" : ""}
                  {fmtPct(data.delta_pct)}
                </td>
                <td className="text-xs text-[var(--faint)]">
                  positive = LLM-only estimates higher
                </td>
              </tr>
            </tbody>
          </table>
          <div className="mt-2 flex flex-wrap items-center gap-1" title="Individual LLM-only run values">
            {data.values.map((value, index) => (
              <span
                key={`${value}-${index}`}
                className="num chip chip-unknown"
                style={{ fontVariantNumeric: "tabular-nums" }}
              >
                {fmtNum(value, 0)}
              </span>
            ))}
          </div>
        </div>

        <div className="panel-2 p-3">
          <div className="mb-1 text-[11px] uppercase tracking-[0.1em] text-[var(--dim)]">
            Distribution of LLM-only answers (days)
          </div>
          <ResponsiveContainer width="100%" height={180}>
            <BarChart data={histogram} margin={{ top: 4, right: 8, bottom: 0, left: -22 }}>
              <XAxis
                dataKey="label"
                tick={{ fill: "var(--faint)", fontSize: 9 }}
                stroke="var(--border)"
              />
              <YAxis
                allowDecimals={false}
                tick={{ fill: "var(--faint)", fontSize: 10 }}
                stroke="var(--border)"
              />
              <ChartTooltip
                cursor={{ fill: "rgba(251,191,36,0.06)" }}
                contentStyle={{
                  background: "#0b1322",
                  border: "1px solid var(--border-strong)",
                  borderRadius: 8,
                  fontSize: 11,
                }}
              />
              <Bar dataKey="count" fill="rgba(251,191,36,0.55)" radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
          <p className="mt-1 text-[11px] text-[var(--faint)]">
            System P50 = <span className="num text-[var(--cyan)]">{fmtNum(data.system_estimate, 0)} d</span>{" "}
            (deterministic — compare the spread, not the single number).
          </p>
        </div>
      </div>

      <p className="text-[11px] leading-5 text-[var(--faint)]">{data.note}</p>
    </div>
  );
}
