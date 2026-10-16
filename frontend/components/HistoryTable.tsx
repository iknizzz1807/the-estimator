"use client";

import { useMemo, useState } from "react";
import type { ProjectRow } from "@/lib/types";
import { FEATURES, featureLabel } from "@/lib/features";
import { deltaTone, fmtInt, fmtPct } from "@/lib/format";
import { EmptyState } from "./ui";
import { GLOSSARY, Term } from "./Tooltip";

const DELTA_CLASS: Record<string, string> = {
  neutral: "text-[var(--text)]",
  warn: "text-[var(--orange)]",
  critical: "text-[var(--red)]",
  none: "text-[var(--faint)]",
};

const STATUS_TONE: Record<string, string> = {
  done: "chip-ok",
  in_progress: "chip-info",
  pending: "chip-unknown",
};

function presentFeatures(row: ProjectRow): string[] {
  return FEATURES.filter((name) => row.features?.[name] === 1);
}

/**
 * History table with client-side filters (status / feature / date range).
 * All 60 projects fit in one fetch, so filtering stays instant — the backend
 * still exposes the same filters for larger datasets.
 */
export function HistoryTable({
  rows,
  onEnterActual,
}: {
  rows: ProjectRow[];
  onEnterActual: (row: ProjectRow) => void;
}) {
  const [status, setStatus] = useState("all");
  const [feature, setFeature] = useState("all");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");

  const statuses = useMemo(
    () => Array.from(new Set(rows.map((row) => row.status))).sort(),
    [rows]
  );

  const filtered = useMemo(
    () =>
      rows.filter((row) => {
        if (status !== "all" && row.status !== status) return false;
        if (feature !== "all" && row.features?.[feature] !== 1) return false;
        if (from && row.date < from) return false;
        if (to && row.date > to) return false;
        return true;
      }),
    [rows, status, feature, from, to]
  );

  const hasFilters = status !== "all" || feature !== "all" || from || to;

  return (
    <div>
      <div className="mb-3 flex flex-wrap items-end gap-3">
        <label className="text-xs text-[var(--dim)]">
          <span className="mb-1 block uppercase tracking-[0.1em]">Status</span>
          <select
            className="select w-40"
            value={status}
            onChange={(event) => setStatus(event.target.value)}
          >
            <option value="all">All</option>
            {statuses.map((value) => (
              <option key={value} value={value}>
                {value}
              </option>
            ))}
          </select>
        </label>
        <label className="text-xs text-[var(--dim)]">
          <span className="mb-1 block uppercase tracking-[0.1em]">Feature</span>
          <select
            className="select w-48"
            value={feature}
            onChange={(event) => setFeature(event.target.value)}
          >
            <option value="all">Any feature</option>
            {FEATURES.map((name) => (
              <option key={name} value={name}>
                {featureLabel(name)}
              </option>
            ))}
          </select>
        </label>
        <label className="text-xs text-[var(--dim)]">
          <span className="mb-1 block uppercase tracking-[0.1em]">From</span>
          <input
            type="date"
            className="input w-40"
            value={from}
            onChange={(event) => setFrom(event.target.value)}
          />
        </label>
        <label className="text-xs text-[var(--dim)]">
          <span className="mb-1 block uppercase tracking-[0.1em]">To</span>
          <input
            type="date"
            className="input w-40"
            value={to}
            onChange={(event) => setTo(event.target.value)}
          />
        </label>
        {hasFilters && (
          <button
            type="button"
            className="btn mb-0.5"
            onClick={() => {
              setStatus("all");
              setFeature("all");
              setFrom("");
              setTo("");
            }}
          >
            Reset
          </button>
        )}
        <span className="num mb-1.5 text-xs text-[var(--faint)]">
          {filtered.length} of {rows.length} projects
        </span>
      </div>

      {filtered.length === 0 ? (
        <EmptyState
          title="No projects match the filters"
          hint="Loosen the status, feature or date range to see rows again."
        />
      ) : (
        <div className="max-h-[62vh] overflow-auto rounded-lg border border-[var(--border)]">
          <table className="data-table">
            <thead>
              <tr>
                <th>Date</th>
                <th>Project</th>
                <th>Status</th>
                <th>Features</th>
                <th title="The team's own estimate at the time">Team est</th>
                <th title="System estimate: P10–P90 band · P50 median">System est</th>
                <th>Actual</th>
                <th>
                  <Term term="Δ%" tip={GLOSSARY.delta}>
                    Δ%
                  </Term>
                </th>
                <th aria-label="Actions" />
              </tr>
            </thead>
            <tbody>
              {filtered.map((row) => {
                const present = presentFeatures(row);
                const tone = deltaTone(row.delta_pct);
                return (
                  <tr key={row.project_id}>
                    <td className="num whitespace-nowrap text-[var(--dim)]">
                      {row.date}
                    </td>
                    <td className="num whitespace-nowrap text-[var(--text)]">
                      {row.project_id}
                    </td>
                    <td>
                      <span className={`chip ${STATUS_TONE[row.status] ?? ""}`}>
                        {row.status}
                      </span>
                    </td>
                    <td>
                      <div
                        className="flex max-w-[230px] flex-wrap gap-1"
                        title={present.map(featureLabel).join(", ") || "No features"}
                      >
                        {present.slice(0, 3).map((name) => (
                          <span key={name} className="chip chip-ok">
                            {featureLabel(name)}
                          </span>
                        ))}
                        {present.length > 3 && (
                          <span className="chip">+{present.length - 3}</span>
                        )}
                        {present.length === 0 && (
                          <span className="text-xs text-[var(--faint)]">—</span>
                        )}
                      </div>
                    </td>
                    <td className="num text-[var(--dim)]">
                      {fmtInt(row.team_estimate)}
                    </td>
                    <td className="num whitespace-nowrap text-[var(--text)]">
                      {row.system_p10 !== null &&
                      row.system_p10 !== undefined &&
                      row.system_p90 !== null &&
                      row.system_p90 !== undefined ? (
                        <>
                          <span className="text-[var(--dim)]">
                            {fmtInt(row.system_p10)}–{fmtInt(row.system_p90)}
                          </span>
                          <span className="text-[var(--faint)]"> · </span>
                          <span className="font-semibold">
                            {fmtInt(row.system_p50)}
                          </span>
                        </>
                      ) : (
                        fmtInt(row.system_p50)
                      )}
                    </td>
                    <td className="num text-[var(--dim)]">
                      {fmtInt(row.actual_days)}
                    </td>
                    <td className={`num whitespace-nowrap ${DELTA_CLASS[tone]}`}>
                      {row.delta_pct === null || row.delta_pct === undefined
                        ? "—"
                        : `${row.delta_pct > 0 ? "+" : ""}${fmtPct(row.delta_pct)}`}
                    </td>
                    <td>
                      {row.status !== "done" && (
                        <button
                          type="button"
                          className="btn btn-warn"
                          onClick={() => onEnterActual(row)}
                        >
                          Enter actual
                        </button>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      <p className="mt-2 text-[11px] text-[var(--faint)]">
        Δ% = (actual − system P50) ÷ system P50. ≤10% neutral, 10–25% review
        (orange), &gt;25% critical (red).
      </p>
    </div>
  );
}
