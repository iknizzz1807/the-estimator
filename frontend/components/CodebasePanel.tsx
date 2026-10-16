"use client";

import type { CodebaseBlock, EstimateRange } from "@/lib/types";
import { fmtInt } from "@/lib/format";
import { Panel, SkeletonLines, Spinner } from "./ui";

/**
 * Codebase Lab panel (contract v0.2): renders the `codebase` block attached by
 * `POST /api/estimate` when a `repo` is selected. Shows structural friction
 * (score + level), the patch shape of similar past changes, the friction /
 * invasiveness adjustments, and the honest-limitations note VERBATIM from the
 * API — the note is part of the product's credibility, never paraphrased.
 */

const LEVEL_META: Record<
  string,
  { label: string; chip: string; bar: string }
> = {
  low: {
    label: "low friction",
    chip: "chip-ok",
    bar: "bg-[var(--lime)]",
  },
  medium: {
    label: "medium friction",
    chip: "chip-unknown",
    bar: "bg-[var(--amber)]",
  },
  high: {
    label: "high friction",
    chip:
      "border-[rgba(248,113,113,0.45)] bg-[rgba(248,113,113,0.08)] text-[#fecaca]",
    bar: "bg-[var(--red)]",
  },
};

const LEVEL_FALLBACK = {
  label: "friction",
  chip: "",
  bar: "bg-[var(--cyan)]",
};

const COMPONENT_LABELS: Record<string, string> = {
  churn: "churn (hot files)",
  fan_in: "fan-in (imports)",
  complexity: "complexity (radon)",
  coverage_gap: "coverage gap",
  author_concentration: "author concentration",
};

function componentTone(value: number): string {
  if (value >= 2 / 3) return "bg-[var(--red)]";
  if (value >= 1 / 3) return "bg-[var(--amber)]";
  return "bg-[var(--lime)]";
}

function RangeWhisker({
  range,
  domainMax,
  tone,
}: {
  range: EstimateRange;
  domainMax: number;
  tone: "base" | "adjusted";
}) {
  const left = Math.max(0, (range.p10 / domainMax) * 100);
  const right = Math.min(100, (range.p90 / domainMax) * 100);
  const median = Math.min(100, Math.max(0, (range.p50 / domainMax) * 100));
  const barClass =
    tone === "base"
      ? "border border-[var(--border-strong)] bg-[rgba(148,163,184,0.18)]"
      : "border border-[rgba(34,211,238,0.7)] bg-[rgba(34,211,238,0.28)]";
  return (
    <div className="relative h-5">
      <div className="absolute inset-x-0 top-1/2 h-px -translate-y-1/2 bg-[var(--border)]" />
      <div
        className={`absolute top-1/2 h-3 -translate-y-1/2 rounded-full ${barClass}`}
        style={{ left: `${left}%`, width: `${Math.max(0.5, right - left)}%` }}
        title={`P10 ${fmtInt(range.p10)} → P90 ${fmtInt(range.p90)} ${range.unit}`}
      />
      <div
        className="absolute top-1/2 h-5 w-[2px] -translate-y-1/2 rounded bg-[var(--lime)]"
        style={{ left: `${median}%` }}
        title={`P50 ${fmtInt(range.p50)} ${range.unit}`}
      />
    </div>
  );
}

export function CodebasePanel({
  codebase,
  loading = false,
  error = null,
  repoLabel,
}: {
  codebase: CodebaseBlock | null;
  loading?: boolean;
  error?: string | null;
  repoLabel?: string;
}) {
  if (loading) {
    return (
      <Panel
        title="Codebase context"
        subtitle={
          repoLabel
            ? `Analyzing ${repoLabel}: git history → friction + similar past changes…`
            : "Analyzing the selected repository…"
        }
      >
        <div className="flex items-center gap-2 text-xs text-[var(--dim)]">
          <Spinner className="h-3.5 w-3.5" />
          collecting signals, matching similar commits, applying friction
        </div>
        <div className="mt-3">
          <SkeletonLines lines={4} />
        </div>
      </Panel>
    );
  }

  if (error) {
    return (
      <Panel title="Codebase context">
        <div className="banner banner-amber" role="alert">
          <span aria-hidden>⚠</span>
          <div className="text-xs">
            <div className="font-medium">Codebase context unavailable</div>
            <div className="opacity-90">{error}</div>
            <div className="opacity-80">
              The estimate above is unaffected — it simply has no codebase
              adjustment attached.
            </div>
          </div>
        </div>
      </Panel>
    );
  }

  if (!codebase) return null;

  const { friction, invasiveness, similar_changes: changes, base_estimate: base, adjusted_estimate: adjusted } = codebase;
  const level = LEVEL_META[friction.level] ?? LEVEL_FALLBACK;
  const domainMax =
    Math.max(base.p90, adjusted.p90, adjusted.p50, base.p50, 1) * 1.08;
  const p50DeltaPct = ((adjusted.p50 - base.p50) / Math.max(base.p50, 0.1)) * 100;
  const p90DeltaPct = ((adjusted.p90 - base.p90) / Math.max(base.p90, 0.1)) * 100;
  const repoName =
    codebase.repo === "demo_a"
      ? "Demo A — plugin pattern"
      : codebase.repo === "demo_b"
        ? "Demo B — spaghetti"
        : codebase.repo === "self"
          ? "This project's checkout"
          : codebase.repo;

  return (
    <Panel
      title={
        <span className="flex flex-wrap items-center gap-2">
          Codebase context
          <span className={`chip ${level.chip}`}>{level.label}</span>
        </span>
      }
      subtitle={
        <>
          Repository: <span className="text-[var(--dim)]">{repoName}</span> — structural
          friction widens the interval; similar past changes shift the median.
          Surcharge only, never a discount.
        </>
      }
    >
      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)]">
        {/* Friction score + components */}
        <div className="panel-2 p-3">
          <div className="flex items-baseline justify-between gap-2">
            <div className="text-[11px] uppercase tracking-[0.1em] text-[var(--dim)]">
              Structural friction
            </div>
            <div className="num text-xl font-semibold text-[var(--text)]">
              {friction.score.toFixed(3)}
            </div>
          </div>
          <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-[#1a2637]">
            <div
              className={`h-full ${level.bar}`}
              style={{ width: `${Math.round(friction.score * 100)}%` }}
            />
          </div>
          <ul className="mt-3 space-y-1.5">
            {Object.entries(friction.components).map(([name, value]) => (
              <li key={name} className="grid grid-cols-[130px_minmax(0,1fr)_auto] items-center gap-2">
                <span className="text-[11px] text-[var(--dim)]">
                  {COMPONENT_LABELS[name] ?? name}
                </span>
                {value === null ? (
                  <span className="text-[10.5px] text-[var(--faint)]">
                    unknown — no report (never faked)
                  </span>
                ) : (
                  <span className="h-1.5 overflow-hidden rounded-full bg-[#1a2637]">
                    <span
                      className={`block h-full ${componentTone(value)}`}
                      style={{ width: `${Math.round(value * 100)}%` }}
                    />
                  </span>
                )}
                <span className="num text-[10.5px] text-[var(--faint)]">
                  {value === null ? "—" : value.toFixed(2)}
                </span>
              </li>
            ))}
          </ul>
        </div>

        {/* Invasiveness + similar past changes */}
        <div className="panel-2 p-3">
          <div className="text-[11px] uppercase tracking-[0.1em] text-[var(--dim)]">
            Similar past changes
          </div>
          {invasiveness ? (
            <p className="mt-1 text-xs leading-5 text-[var(--dim)]">
              {invasiveness.based_on_commits} matched commit
              {invasiveness.based_on_commits === 1 ? "" : "s"} touched{" "}
              <span className="num text-[var(--text)]">
                {invasiveness.mean_files_touched}
              </span>{" "}
              files on average;{" "}
              <span className="num text-[var(--text)]">
                {Math.round(invasiveness.modified_ratio * 100)}%
              </span>{" "}
              were modifications of existing files (invasiveness → P50 shift).
            </p>
          ) : (
            <p className="mt-1 text-xs leading-5 text-[var(--dim)]">
              No similar past changes matched the feature keywords — no
              evidence, so the median is unchanged (never a fabricated shift).
            </p>
          )}
          {changes.length > 0 && (
            <ul className="mt-2 space-y-1.5">
              {changes.map((change) => (
                <li
                  key={change.commit}
                  className="flex flex-wrap items-center gap-x-2 gap-y-1 rounded-md border border-[var(--border)] px-2.5 py-1.5"
                >
                  <span className="num text-[11px] text-[var(--cyan)]">
                    {change.commit}
                  </span>
                  <span className="num text-[11px] text-[var(--dim)]">
                    {change.date}
                  </span>
                  <span className="text-[11px] text-[var(--dim)]">
                    {change.files_touched} file{change.files_touched === 1 ? "" : "s"}
                  </span>
                  <span className="chip chip-ok">+{change.new_files} new</span>
                  <span className="chip chip-unknown">
                    ~{change.modified_files} modified
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>

      {/* Base → adjusted range visual */}
      <div className="panel-2 mt-4 p-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="text-[11px] uppercase tracking-[0.1em] text-[var(--dim)]">
            Estimate before vs after codebase adjustment
          </div>
          <div className="flex flex-wrap items-center gap-1.5">
            {Math.abs(p50DeltaPct) >= 0.5 && (
              <span
                className="chip chip-unknown num"
                title="Median shift from invasiveness (P50 × (1 + 0.35 × modified ratio))"
              >
                P50 {p50DeltaPct > 0 ? "+" : "−"}
                {Math.abs(p50DeltaPct).toFixed(0)}%
              </span>
            )}
            {Math.abs(p90DeltaPct) >= 0.5 && (
              <span
                className="chip chip-unknown num"
                title="Upper-tail widening from friction (P90 × (1 + 0.60 × score))"
              >
                P90 {p90DeltaPct > 0 ? "+" : "−"}
                {Math.abs(p90DeltaPct).toFixed(0)}%
              </span>
            )}
            <span className="chip chip-off">one-directional</span>
          </div>
        </div>
        <div className="mt-2 grid grid-cols-[54px_minmax(0,1fr)_auto] items-center gap-x-3 gap-y-1.5">
          <span className="text-[10px] uppercase tracking-wider text-[var(--faint)]">
            Base
          </span>
          <RangeWhisker range={base} domainMax={domainMax} tone="base" />
          <span className="num whitespace-nowrap text-[11px] text-[var(--dim)]">
            {fmtInt(base.p10)}–{fmtInt(base.p90)}{" "}
            <span className="text-[var(--faint)]">(P50 {fmtInt(base.p50)})</span>
          </span>

          <span className="text-[10px] uppercase tracking-wider text-[var(--cyan)]">
            Adjusted
          </span>
          <RangeWhisker range={adjusted} domainMax={domainMax} tone="adjusted" />
          <span className="num whitespace-nowrap text-[11px] text-[var(--cyan)]">
            {fmtInt(adjusted.p10)}–{fmtInt(adjusted.p90)}{" "}
            <span className="text-[var(--faint)]">
              (P50 {fmtInt(adjusted.p50)})
            </span>
          </span>
        </div>
        <ul className="mt-3 space-y-1">
          {codebase.adjustments.map((adjustment) => (
            <li
              key={adjustment.what}
              className="flex flex-wrap items-start gap-2 text-[11px] leading-4 text-[var(--dim)]"
            >
              <span className="chip chip-info num shrink-0">
                ×{adjustment.factor.toFixed(2)}
              </span>
              <span>
                <span className="font-medium text-[var(--text)]">
                  {adjustment.what}
                </span>{" "}
                — {adjustment.why}
              </span>
            </li>
          ))}
        </ul>
      </div>

      {/* Honest note — verbatim from the API (docs/API.md v0.2). */}
      <p className="mt-3 rounded-md border border-[var(--border)] bg-[rgba(148,163,184,0.05)] p-2.5 text-[10.5px] leading-4 text-[var(--faint)]">
        {codebase.note}
      </p>
    </Panel>
  );
}
