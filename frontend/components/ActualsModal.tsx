"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import { useAsyncAction } from "@/lib/hooks";
import type { ActualUpdateResponse, ProjectRow } from "@/lib/types";
import { featureLabel } from "@/lib/features";
import { fmtInt, fmtNum, fmtPct } from "@/lib/format";
import { Spinner } from "./ui";

const MAX_SANE_DAYS = 1000;

/**
 * Enter actuals for a finished project (POST /api/projects/{id}/actual).
 * Spec §9 validation: reject ≤ 0 inline; > 1000 shows an amber warning but
 * is allowed. On success the coefficient updates and accuracy delta are shown
 * — the visible payoff of the learning loop (spec §3.3).
 */
export function ActualsModal({
  row,
  onClose,
  onSaved,
}: {
  row: ProjectRow;
  onClose: () => void;
  onSaved: (result: ActualUpdateResponse) => void;
}) {
  const [value, setValue] = useState("");
  const [localError, setLocalError] = useState<string | null>(null);
  const [result, setResult] = useState<ActualUpdateResponse | null>(null);
  const { run, loading, error } = useAsyncAction(
    async (projectId: string, days: number) => api.submitActual(projectId, days)
  );

  const numeric = Number(value.replace(",", "."));
  const isNumber = value.trim() !== "" && Number.isFinite(numeric);
  const tooSmall = isNumber && numeric <= 0;
  const tooLarge = isNumber && numeric > MAX_SANE_DAYS;

  const submit = async () => {
    setLocalError(null);
    if (!isNumber) {
      setLocalError("Enter the number of days as a number (e.g. 42).");
      return;
    }
    if (tooSmall) {
      setLocalError("actual_days must be greater than 0 — the API rejects it (422).");
      return;
    }
    const response = await run(row.project_id, numeric);
    if (response) {
      setResult(response);
      onSaved(response);
    }
  };

  const deltaClass = (delta: number | null | undefined) =>
    delta === null || delta === undefined
      ? "text-[var(--faint)]"
      : Math.abs(delta) <= 10
        ? "text-[var(--text)]"
        : Math.abs(delta) <= 25
          ? "text-[var(--orange)]"
          : "text-[var(--red)]";

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4"
      role="dialog"
      aria-modal="true"
      aria-label={`Enter actual days for ${row.project_id}`}
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div className="panel max-h-[88vh] w-full max-w-lg overflow-auto p-5">
        <div className="mb-3 flex items-start justify-between gap-3">
          <div>
            <h2 className="text-lg font-semibold">
              Enter actuals — <span className="num">{row.project_id}</span>
            </h2>
            <p className="mt-1 text-xs text-[var(--faint)]">
              System estimate: P50 {fmtInt(row.system_p50)} days
              {row.system_p10 != null && row.system_p90 != null
                ? ` (range ${fmtInt(row.system_p10)}–${fmtInt(row.system_p90)})`
                : ""}{" "}
              · this becomes a training sample immediately.
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
                Actual effort (days)
              </span>
              <input
                type="number"
                min={1}
                step="1"
                inputMode="decimal"
                className="input num"
                placeholder="e.g. 42"
                value={value}
                onChange={(event) => {
                  setValue(event.target.value);
                  setLocalError(null);
                }}
                onKeyDown={(event) => {
                  if (event.key === "Enter" && !loading) void submit();
                }}
              />
            </label>

            {tooLarge && (
              <div className="banner banner-amber" role="alert">
                <span aria-hidden>⚠</span>
                <span className="text-xs">
                  Unusual value (&gt; {MAX_SANE_DAYS} days) — accepted, but please
                  double-check before trusting the updated coefficients.
                </span>
              </div>
            )}

            {(localError || error) && (
              <div className="banner banner-red" role="alert">
                <span aria-hidden>✕</span>
                <div className="text-xs">
                  <div className="font-medium">Could not save</div>
                  <div className="opacity-90">{localError ?? error}</div>
                  <div className="opacity-80">
                    {localError
                      ? "Fix the value and submit again."
                      : "Check the backend, then retry — the value was not saved."}
                  </div>
                </div>
              </div>
            )}

            <div className="flex justify-end gap-2">
              <button type="button" className="btn" onClick={onClose}>
                Cancel
              </button>
              <button
                type="button"
                className="btn btn-primary"
                disabled={loading || !value.trim()}
                onClick={submit}
              >
                {loading ? <Spinner className="h-3.5 w-3.5" /> : null}
                {loading ? "Saving…" : "Save actual"}
              </button>
            </div>
          </div>
        )}

        {result && (
          <div className="space-y-3">
            <div className="flex flex-wrap items-center gap-2 text-xs">
              <span className="chip chip-ok">actual saved</span>
              <span className={`num ${deltaClass(result.project.delta_pct)}`}>
                {result.project.delta_pct === null
                  ? "Δ unknown"
                  : `project Δ ${result.project.delta_pct > 0 ? "+" : ""}${fmtPct(result.project.delta_pct)}`}
              </span>
            </div>

            {result.warning && (
              <div className="banner banner-amber" role="alert">
                <span aria-hidden>⚠</span>
                <span className="text-xs">{result.warning}</span>
              </div>
            )}

            <div>
              <h3 className="mb-1.5 text-xs uppercase tracking-[0.1em] text-[var(--dim)]">
                Coefficient updates
              </h3>
              {result.coefficient_updates.length === 0 ? (
                <p className="text-xs text-[var(--faint)]">
                  No coefficient needed an update this time.
                </p>
              ) : (
                <ul className="space-y-1.5">
                  {result.coefficient_updates.map((update) => {
                    const up = update.new >= update.old;
                    return (
                      <li
                        key={update.feature}
                        className="panel-2 flex items-center justify-between gap-2 px-3 py-2 text-xs"
                      >
                        <span className="text-[var(--dim)]">
                          {featureLabel(update.feature)}
                        </span>
                        <span className="num flex items-center gap-1.5">
                          <span className="text-[var(--faint)]">
                            {fmtNum(update.old, 2)}
                          </span>
                          <span className={up ? "text-[var(--amber)]" : "text-[var(--cyan)]"}>
                            →
                          </span>
                          <span className="text-[var(--text)]">
                            {fmtNum(update.new, 2)}
                          </span>
                          <span className="text-[var(--faint)]">
                            (n={update.sample_count})
                          </span>
                        </span>
                      </li>
                    );
                  })}
                </ul>
              )}
            </div>

            <div>
              <h3 className="mb-1.5 text-xs uppercase tracking-[0.1em] text-[var(--dim)]">
                Accuracy impact
              </h3>
              <div className="panel-2 grid grid-cols-3 gap-2 px-3 py-2 text-xs">
                <div>
                  <div className="text-[var(--faint)]">MAE before</div>
                  <div className="num text-[var(--text)]">
                    {fmtNum(result.accuracy.mae_before, 1)}
                  </div>
                </div>
                <div>
                  <div className="text-[var(--faint)]">MAE after</div>
                  <div
                    className={`num ${
                      result.accuracy.mae_after <= result.accuracy.mae_before
                        ? "text-[var(--lime)]"
                        : "text-[var(--amber)]"
                    }`}
                  >
                    {fmtNum(result.accuracy.mae_after, 1)}
                  </div>
                </div>
                <div>
                  <div className="text-[var(--faint)]">Coverage</div>
                  <div className="num text-[var(--text)]">
                    {fmtPct(result.accuracy.coverage_pct)}
                  </div>
                </div>
              </div>
            </div>

            <div className="flex justify-end">
              <button type="button" className="btn btn-primary" onClick={onClose}>
                Done
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
