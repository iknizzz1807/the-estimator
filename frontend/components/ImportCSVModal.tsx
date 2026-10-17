"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import { fmtInt } from "@/lib/format";
import { useAsyncAction } from "@/lib/hooks";
import type { Scenario } from "@/lib/types";
import { Spinner } from "./ui";

/**
 * CSV import (POST /api/import, multipart). Field name is "file" — the
 * contract only says "multipart CSV", so the UI states the expectation.
 */
export function ImportCSVModal({
  onClose,
  onViewHistory,
}: {
  onClose: () => void;
  onViewHistory: () => void;
}) {
  const [file, setFile] = useState<File | null>(null);
  const [result, setResult] = useState<{
    imported: number;
    skipped: number;
    errors: string[];
  } | null>(null);
  const { run, loading, error } = useAsyncAction(async (f: File) =>
    api.importCsv(f)
  );

  const submit = async () => {
    if (!file) return;
    const res = await run(file);
    if (res) setResult(res);
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-[var(--overlay)]/85 backdrop-blur-sm p-4"
      role="dialog"
      aria-modal="true"
      aria-label="Import CSV"
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div className="panel w-full max-w-xl p-5 border border-[var(--hairline-strong)] shadow-[0_24px_56px_rgba(0,0,0,0.95)]">
        <div className="mb-3 flex items-start justify-between gap-3">
          <div>
            <h2 className="text-lg font-semibold">Import project history (CSV)</h2>
            <p className="mt-1 text-xs text-[var(--faint)]">
              One row per project. Columns must match{" "}
              <code className="num">data/synthetic_history.csv</code> —
              including the 15 <code className="num">feat_*</code> columns.
            </p>
          </div>
          <button type="button" className="btn" onClick={onClose} aria-label="Close">
            ✕
          </button>
        </div>

        {!result && (
          <div className="space-y-3">
            <label className="block">
              <span className="mb-1 block text-xs uppercase tracking-[0.1em] text-[var(--dim)]">
                CSV file
              </span>
              <input
                type="file"
                accept=".csv,text/csv"
                className="input"
                onChange={(event) => setFile(event.target.files?.[0] ?? null)}
              />
            </label>
            <ul className="space-y-1 text-xs text-[var(--faint)]">
              <li>
                · <code className="num">actual_days</code> must be empty when{" "}
                <code className="num">status != done</code>.
              </li>
              <li>
                · <code className="num">is_synthetic</code> = 0|1; feature
                columns = 0|1.
              </li>
              <li>· Invalid rows are skipped and reported — never silently dropped.</li>
            </ul>

            {error && (
              <div className="banner banner-red" role="alert">
                <span aria-hidden>✕</span>
                <div>
                  <div className="font-medium">Import failed</div>
                  <div className="text-xs opacity-90">{error}</div>
                  {error.includes("400") || error.includes("422") ? (
                    <div className="text-xs opacity-80">
                      Check the column order against the CSV spec, then try again.
                    </div>
                  ) : (
                    <div className="text-xs opacity-80">
                      Is the backend running? Retry — or fix the file and submit again.
                    </div>
                  )}
                </div>
              </div>
            )}

            <div className="flex justify-end gap-2 pt-1">
              <button type="button" className="btn" onClick={onClose}>
                Cancel
              </button>
              <button
                type="button"
                className="btn btn-primary"
                disabled={!file || loading}
                onClick={submit}
              >
                {loading ? <Spinner className="h-3.5 w-3.5" /> : null}
                {loading ? "Importing…" : "Import"}
              </button>
            </div>
          </div>
        )}

        {result && (
          <div className="space-y-3">
            <div className="flex flex-wrap gap-2">
              <span className="chip chip-ok">
                {fmtInt(result.imported)} imported
              </span>
              <span className="chip chip-unknown">
                {fmtInt(result.skipped)} skipped
              </span>
            </div>
            {result.errors.length > 0 ? (
              <div className="banner banner-amber" role="alert">
                <span aria-hidden>⚠</span>
                <div className="text-xs">
                  <div className="font-medium">
                    {result.errors.length} row{result.errors.length > 1 ? "s" : ""}{" "}
                    rejected — review before trusting the new history
                  </div>
                  <ul className="mt-1 list-inside list-disc space-y-0.5 opacity-90">
                    {result.errors.map((message) => (
                      <li key={message} className="num">
                        {message}
                      </li>
                    ))}
                  </ul>
                </div>
              </div>
            ) : (
              <div className="banner banner-lime" role="status">
                <span aria-hidden>✓</span>
                <div className="text-xs">
                  All rows imported. New rows become training samples immediately.
                </div>
              </div>
            )}
            <div className="flex justify-end gap-2">
              <button type="button" className="btn" onClick={onClose}>
                Close
              </button>
              <button type="button" className="btn btn-primary" onClick={onViewHistory}>
                View History →
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

/** Scenario dropdown shared by the Estimate screen. */
export function ScenarioPicker({
  scenarios,
  loading,
  onPick,
  disabled,
}: {
  scenarios: Scenario[];
  loading: boolean;
  onPick: (scenario: Scenario) => void;
  disabled?: boolean;
}) {
  const [selected, setSelected] = useState("");
  if (loading) {
    return (
      <div className="flex items-center gap-2 text-xs text-[var(--faint)]">
        <Spinner className="h-3.5 w-3.5" /> Loading sample scenarios…
      </div>
    );
  }
  if (scenarios.length === 0) return null;
  return (
    <div className="flex flex-wrap items-center gap-2">
      <label className="text-xs text-[var(--dim)]" htmlFor="scenario-select">
        Sample scenario
      </label>
      <select
        id="scenario-select"
        className="select w-64"
        value={selected}
        disabled={disabled}
        onChange={(event) => setSelected(event.target.value)}
      >
        <option value="">Choose a scenario…</option>
        {scenarios.map((scenario) => (
          <option key={scenario.id} value={scenario.id}>
            {scenario.id} — {scenario.title}
          </option>
        ))}
      </select>
      <button
        type="button"
        className="btn"
        disabled={!selected || disabled}
        onClick={() => {
          const scenario = scenarios.find((s) => s.id === selected);
          if (scenario) onPick(scenario);
        }}
      >
        Paste into editor
      </button>
    </div>
  );
}
