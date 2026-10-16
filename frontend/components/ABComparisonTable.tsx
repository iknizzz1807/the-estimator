"use client";

import {
  Bar,
  BarChart,
  ResponsiveContainer,
  Tooltip as ChartTooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { ABResponse, HistoryBaseline } from "@/lib/types";
import { fmtNum, fmtPct } from "@/lib/format";
import { Term } from "./Tooltip";

function SimulatedChip() {
  return (
    <span
      className="chip chip-unknown"
      title="No API key configured — this baseline is emulated with seeded noise, not measured on a real LLM"
    >
      simulated
    </span>
  );
}

function deltaClass(deltaPct: number | null | undefined): string {
  const value = Math.abs(deltaPct ?? 0);
  if (value <= 5) return "text-[var(--text)]";
  if (value <= 15) return "text-[var(--orange)]";
  return "text-[var(--red)]";
}

/**
 * A/B comparison (spec §4.5): LLM-only runs of the same email vs the system
 * estimate, plus the "LLM + company history" baseline (contract v0.2) — the
 * fair strawman that gets the recent finished projects in its prompt.
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

  const history: HistoryBaseline | null =
    data.baseline_history && data.baseline_history.n > 0
      ? data.baseline_history
      : null;
  const hasHistory = history !== null;
  const historyMin = history
    ? history.min ?? Math.min(...history.values)
    : null;
  const historyMax = history
    ? history.max ?? Math.max(...history.values)
    : null;
  const historyDeltaPct =
    history && data.system_estimate
      ? Number(
          (((history.mean - data.system_estimate) / data.system_estimate) * 100).toFixed(1)
        )
      : null;
  const nRuns = data.n ?? data.values.length;

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
          n = {nRuns} runs
          {typeof data.errors === "number" && data.errors > 0
            ? ` · ${data.errors} failed`
            : ""}
        </span>
      </div>

      <div className="grid gap-3 lg:grid-cols-2">
        <div>
          <table className="data-table">
            <thead>
              <tr>
                <th>Statistic</th>
                <th>LLM-only</th>
                {hasHistory && (
                  <th>
                    <span className="flex flex-wrap items-center gap-1.5">
                      LLM + company history
                      {history.mode === "simulated" && <SimulatedChip />}
                    </span>
                  </th>
                )}
                <th>Context</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td>Mean</td>
                <td className="num text-[var(--amber)]">{fmtNum(data.mean, 1)} d</td>
                {hasHistory && (
                  <td className="num text-[var(--lime)]">
                    {fmtNum(history.mean, 1)} d
                  </td>
                )}
                <td className="text-xs text-[var(--faint)]">
                  average of {nRuns} single-number answers
                  {hasHistory ? ` (history: ${history.n} runs with recent actuals)` : ""}
                </td>
              </tr>
              <tr>
                <td>
                  <Term term="Std dev" tip="Spread of the answers across runs — the system should be far more consistent than this.">
                    Std dev
                  </Term>
                </td>
                <td className="num text-[var(--amber)]">{fmtNum(data.std, 2)} d</td>
                {hasHistory && (
                  <td className="num text-[var(--lime)]">{fmtNum(history.std, 2)} d</td>
                )}
                <td className="text-xs text-[var(--faint)]">
                  run-to-run variance; lower is better
                </td>
              </tr>
              <tr>
                <td>Min / Max</td>
                <td className="num text-[var(--amber)]">
                  {fmtNum(data.min, 0)} / {fmtNum(data.max, 0)} d
                </td>
                {hasHistory && (
                  <td className="num text-[var(--lime)]">
                    {fmtNum(historyMin, 0)} / {fmtNum(historyMax, 0)} d
                  </td>
                )}
                <td className="text-xs text-[var(--faint)]">
                  spread of ±{fmtNum((data.max - data.min) / 2, 1)} days around the
                  LLM-only mean
                </td>
              </tr>
              <tr>
                <td>System estimate</td>
                <td
                  colSpan={hasHistory ? 2 : 1}
                  className="num text-[var(--cyan)]"
                >
                  {fmtNum(data.system_estimate, 0)} d (P50)
                </td>
                <td className="text-xs text-[var(--faint)]">
                  same email through the full pipeline — deterministic
                </td>
              </tr>
              <tr>
                <td>Δ mean vs system</td>
                <td className={`num ${deltaClass(data.delta_pct)}`}>
                  {data.delta_pct > 0 ? "+" : ""}
                  {fmtPct(data.delta_pct)}
                </td>
                {hasHistory && (
                  <td className={`num ${deltaClass(historyDeltaPct)}`}>
                    {historyDeltaPct !== null && historyDeltaPct > 0 ? "+" : ""}
                    {fmtPct(historyDeltaPct)}
                  </td>
                )}
                <td className="text-xs text-[var(--faint)]">
                  positive = baseline estimates higher than the system
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
          {hasHistory && (
            <div
              className="mt-1.5 flex flex-wrap items-center gap-1"
              title="Individual LLM-with-history run values"
            >
              <span className="text-[10.5px] uppercase tracking-wider text-[var(--faint)]">
                +history
              </span>
              {history.values.map((value, index) => (
                <span
                  key={`h-${value}-${index}`}
                  className="num chip chip-info"
                  style={{ fontVariantNumeric: "tabular-nums" }}
                >
                  {fmtNum(value, 0)}
                </span>
              ))}
            </div>
          )}
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
            System P50 ={" "}
            <span className="num text-[var(--cyan)]">
              {fmtNum(data.system_estimate, 0)} d
            </span>{" "}
            (deterministic — compare the spread, not the single number).
            {hasHistory && history && (
              <>
                {" "}
                LLM + company history:{" "}
                <span className="num text-[var(--lime)]">
                  {fmtNum(history.mean, 1)} d
                </span>{" "}
                mean, {fmtNum(history.std, 2)} d std
                {history.mode === "simulated" ? " (simulated)" : ""}.
              </>
            )}
          </p>
        </div>
      </div>

      <p className="text-[11px] leading-5 text-[var(--faint)]">{data.note}</p>
    </div>
  );
}
