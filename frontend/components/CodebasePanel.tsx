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
 *
 * Styled strictly to Linear design system: Surface-1 panels (#0f1011),
 * hairline borders (#23252a), changelog-style commit rows (#010102 / #0f1011),
 * and Linear lavender accents (#5e6ad2).
 */

const LEVEL_META: Record<
  string,
  { label: string; pill: string; bar: string }
> = {
  low: {
    label: "Low friction",
    pill: "border-[rgba(39,166,68,0.3)] bg-[rgba(39,166,68,0.1)] text-[#27a644]",
    bar: "bg-[#27a644]",
  },
  medium: {
    label: "Medium friction",
    pill: "border-[rgba(245,158,11,0.3)] bg-[rgba(245,158,11,0.1)] text-[#f59e0b]",
    bar: "bg-[#f59e0b]",
  },
  high: {
    label: "High friction",
    pill: "border-[rgba(235,87,87,0.3)] bg-[rgba(235,87,87,0.1)] text-[#eb5757]",
    bar: "bg-[#eb5757]",
  },
};

const LEVEL_FALLBACK = {
  label: "Friction",
  pill: "border-[#23252a] bg-[#141516] text-[#8a8f98]",
  bar: "bg-[#5e6ad2]",
};

const COMPONENT_LABELS: Record<string, string> = {
  churn: "Churn (hot files)",
  fan_in: "Fan-in (imports)",
  complexity: "Complexity (radon)",
  coverage_gap: "Coverage gap",
  author_concentration: "Author concentration",
};

function componentTone(value: number): string {
  if (value >= 2 / 3) return "bg-[#eb5757]";
  if (value >= 1 / 3) return "bg-[#f59e0b]";
  return "bg-[#27a644]";
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
      ? "border border-[#34343a] bg-[#18191a]"
      : "border border-[#5e6ad2] bg-[rgba(94,106,210,0.2)]";

  return (
    <div className="relative h-5">
      <div className="absolute inset-x-0 top-1/2 h-px -translate-y-1/2 bg-[#23252a]" />
      <div
        className={`absolute top-1/2 h-2.5 -translate-y-1/2 rounded-full ${barClass}`}
        style={{ left: `${left}%`, width: `${Math.max(1, right - left)}%` }}
        title={`P10 ${fmtInt(range.p10)} → P90 ${fmtInt(range.p90)} ${range.unit}`}
      />
      <div
        className={`absolute top-1/2 h-4 w-[2px] -translate-y-1/2 rounded ${
          tone === "base" ? "bg-[#8a8f98]" : "bg-[#5e6ad2]"
        }`}
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
        <div className="flex items-center gap-2 text-xs text-[#8a8f98]">
          <Spinner className="h-3.5 w-3.5" />
          <span>Collecting signals, matching similar commits, applying structural friction…</span>
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
        <div
          className="flex items-center gap-2 rounded-lg border border-[rgba(245,158,11,0.3)] bg-[rgba(245,158,11,0.08)] p-3 text-xs text-[#f59e0b]"
          role="alert"
        >
          <span aria-hidden>⚠</span>
          <div>
            <div className="font-semibold">Codebase context unavailable</div>
            <div className="opacity-90">{error}</div>
            <div className="mt-0.5 text-[11px] text-[#8a8f98]">
              The estimate above is unaffected — it simply has no codebase adjustment attached.
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
      ? "Demo A (Plugin pattern)"
      : codebase.repo === "demo_b"
        ? "Demo B (Spaghetti)"
        : codebase.repo === "self"
          ? "This project's checkout"
          : codebase.repo;

  return (
    <Panel
      title={
        <span className="flex flex-wrap items-center gap-2">
          Codebase context
          <span className={`inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-[11px] font-medium tracking-wide ${level.pill}`}>
            <span className={`h-1.5 w-1.5 rounded-full ${level.bar}`} />
            {level.label}
          </span>
        </span>
      }
      subtitle={
        <>
          Repository: <span className="font-medium text-[#f7f8f8]">{repoName}</span> — structural
          friction widens the interval; similar past changes shift the median. Surcharge only, never a discount.
        </>
      }
    >
      <div className="space-y-4">
        <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)]">
          {/* Friction score + components */}
          <div className="rounded-lg border border-[#23252a] bg-[#0f1011] p-4">
            <div className="flex items-baseline justify-between gap-2 border-b border-[#23252a]/70 pb-2.5">
              <div className="text-[11px] font-medium uppercase tracking-[0.1em] text-[#8a8f98]">
                Structural friction
              </div>
              <div className="font-mono text-xl font-bold tabular-nums text-[#f7f8f8]">
                {friction.score.toFixed(3)}
              </div>
            </div>

            <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-[#18191a]">
              <div
                className={`h-full ${level.bar}`}
                style={{ width: `${Math.round(friction.score * 100)}%` }}
              />
            </div>

            <ul className="mt-4 space-y-2">
              {Object.entries(friction.components).map(([name, value]) => (
                <li key={name} className="grid grid-cols-[130px_minmax(0,1fr)_auto] items-center gap-2 text-xs">
                  <span className="truncate text-[#8a8f98]">
                    {COMPONENT_LABELS[name] ?? name}
                  </span>
                  {value === null ? (
                    <span className="text-[10.5px] italic text-[#62666d]">
                      unknown — no report
                    </span>
                  ) : (
                    <span className="h-1.5 overflow-hidden rounded-full bg-[#18191a]">
                      <span
                        className={`block h-full ${componentTone(value)}`}
                        style={{ width: `${Math.round(value * 100)}%` }}
                      />
                    </span>
                  )}
                  <span className="font-mono text-[10.5px] tabular-nums text-[#62666d]">
                    {value === null ? "—" : value.toFixed(2)}
                  </span>
                </li>
              ))}
            </ul>
          </div>

          {/* Invasiveness + Changelog-style Similar Past Changes */}
          <div className="rounded-lg border border-[#23252a] bg-[#0f1011] p-4">
            <div className="text-[11px] font-medium uppercase tracking-[0.1em] text-[#8a8f98]">
              Similar past changes
            </div>
            {invasiveness ? (
              <p className="mt-1.5 text-xs leading-relaxed text-[#8a8f98]">
                <span className="font-semibold text-[#f7f8f8]">{invasiveness.based_on_commits}</span> matched commit
                {invasiveness.based_on_commits === 1 ? "" : "s"} touched{" "}
                <span className="font-mono text-[#f7f8f8]">
                  {invasiveness.mean_files_touched}
                </span>{" "}
                files on average;{" "}
                <span className="font-mono text-[#f7f8f8]">
                  {Math.round(invasiveness.modified_ratio * 100)}%
                </span>{" "}
                were modifications of existing files.
              </p>
            ) : (
              <p className="mt-1.5 text-xs leading-relaxed text-[#62666d]">
                No similar past changes matched the feature keywords — no evidence, so median is unchanged.
              </p>
            )}

            {/* Changelog-row styled commits: background #010102 with hairline dividers */}
            {changes.length > 0 && (
              <div className="mt-3 divide-y divide-[#23252a] rounded-lg border border-[#23252a] bg-[#010102] px-3.5">
                {changes.map((change) => (
                  <div
                    key={change.commit}
                    className="flex flex-wrap items-center justify-between gap-x-2 gap-y-1.5 py-2.5 text-xs"
                  >
                    <div className="flex items-center gap-2">
                      <span className="font-mono font-medium text-[#5e6ad2]">
                        {change.commit}
                      </span>
                      <span className="font-mono text-[11px] text-[#62666d]">
                        {change.date}
                      </span>
                      <span className="text-[#8a8f98]">
                        {change.files_touched} file{change.files_touched === 1 ? "" : "s"}
                      </span>
                    </div>

                    <div className="flex items-center gap-1.5">
                      <span className="inline-flex items-center rounded-full border border-[rgba(39,166,68,0.3)] bg-[rgba(39,166,68,0.1)] px-2 py-0.5 font-mono text-[10px] tabular-nums text-[#27a644]">
                        +{change.new_files} new
                      </span>
                      <span className="inline-flex items-center rounded-full border border-[rgba(245,158,11,0.3)] bg-[rgba(245,158,11,0.1)] px-2 py-0.5 font-mono text-[10px] tabular-nums text-[#f59e0b]">
                        ~{change.modified_files} mod
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* Base → Adjusted Range Visual */}
        <div className="rounded-lg border border-[#23252a] bg-[#0f1011] p-4">
          <div className="flex flex-wrap items-center justify-between gap-2 border-b border-[#23252a]/70 pb-2.5">
            <div className="text-[11px] font-medium uppercase tracking-[0.1em] text-[#8a8f98]">
              Estimate before vs after codebase adjustment
            </div>

            <div className="flex flex-wrap items-center gap-1.5">
              {Math.abs(p50DeltaPct) >= 0.5 && (
                <span
                  className="inline-flex items-center rounded-full border border-[rgba(94,106,210,0.3)] bg-[rgba(94,106,210,0.1)] px-2 py-0.5 font-mono text-[10.5px] tabular-nums text-[#828fff]"
                  title="Median shift from invasiveness (P50 × (1 + 0.35 × modified ratio))"
                >
                  P50 {p50DeltaPct > 0 ? "+" : "−"}
                  {Math.abs(p50DeltaPct).toFixed(0)}%
                </span>
              )}
              {Math.abs(p90DeltaPct) >= 0.5 && (
                <span
                  className="inline-flex items-center rounded-full border border-[rgba(245,158,11,0.3)] bg-[rgba(245,158,11,0.1)] px-2 py-0.5 font-mono text-[10.5px] tabular-nums text-[#f59e0b]"
                  title="Upper-tail widening from friction (P90 × (1 + 0.60 × score))"
                >
                  P90 {p90DeltaPct > 0 ? "+" : "−"}
                  {Math.abs(p90DeltaPct).toFixed(0)}%
                </span>
              )}
              <span className="inline-flex items-center rounded-full border border-[#23252a] bg-[#141516] px-2 py-0.5 text-[10px] text-[#62666d]">
                one-directional
              </span>
            </div>
          </div>

          <div className="mt-3 grid grid-cols-[60px_minmax(0,1fr)_auto] items-center gap-x-3 gap-y-2">
            <span className="text-[10px] font-medium uppercase tracking-wider text-[#62666d]">
              Base
            </span>
            <RangeWhisker range={base} domainMax={domainMax} tone="base" />
            <span className="font-mono text-xs tabular-nums text-[#8a8f98]">
              {fmtInt(base.p10)}–{fmtInt(base.p90)}{" "}
              <span className="text-[#62666d]">(P50 {fmtInt(base.p50)})</span>
            </span>

            <span className="text-[10px] font-medium uppercase tracking-wider text-[#828fff]">
              Adjusted
            </span>
            <RangeWhisker range={adjusted} domainMax={domainMax} tone="adjusted" />
            <span className="font-mono text-xs font-semibold tabular-nums text-[#828fff]">
              {fmtInt(adjusted.p10)}–{fmtInt(adjusted.p90)}{" "}
              <span className="text-[#8a8f98]">(P50 {fmtInt(adjusted.p50)})</span>
            </span>
          </div>

          <ul className="mt-4 space-y-1.5 border-t border-[#23252a]/70 pt-3">
            {codebase.adjustments.map((adjustment) => (
              <li
                key={adjustment.what}
                className="flex flex-wrap items-start gap-2 text-xs leading-relaxed text-[#8a8f98]"
              >
                <span className="inline-flex items-center rounded border border-[#23252a] bg-[#141516] px-1.5 py-0.5 font-mono text-[10.5px] tabular-nums font-semibold text-[#828fff]">
                  ×{adjustment.factor.toFixed(2)}
                </span>
                <span>
                  <strong className="font-semibold text-[#f7f8f8]">
                    {adjustment.what}
                  </strong>{" "}
                  — {adjustment.why}
                </span>
              </li>
            ))}
          </ul>
        </div>

        {/* Verbatim limitations note on #010102 */}
        <p className="rounded-lg border border-[#23252a] bg-[#010102] p-3 text-[11px] leading-relaxed text-[#8a8f98]">
          {codebase.note}
        </p>
      </div>
    </Panel>
  );
}
