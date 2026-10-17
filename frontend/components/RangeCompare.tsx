"use client";

import type { EstimateRange } from "@/lib/types";
import { fmtInt } from "@/lib/format";
import { GLOSSARY, Term } from "./Tooltip";

function Whisker({
  range,
  domainMax,
  tone,
}: {
  range: EstimateRange;
  domainMax: number;
  tone: "before" | "after";
}) {
  const left = Math.max(0, (range.p10 / domainMax) * 100);
  const right = Math.min(100, (range.p90 / domainMax) * 100);
  const median = Math.min(100, Math.max(0, (range.p50 / domainMax) * 100));
  const barClass =
    tone === "before"
      ? "border border-[var(--hairline-strong)] bg-[var(--surface-3)]"
      : "border border-[var(--primary)] bg-[rgba(94,106,210,0.25)]";
  return (
    <div className="relative h-5">
      <div className="absolute inset-x-0 top-1/2 h-px -translate-y-1/2 bg-[var(--hairline)]" />
      <div
        className={`absolute top-1/2 h-3 -translate-y-1/2 rounded-full ${barClass}`}
        style={{ left: `${left}%`, width: `${Math.max(0.5, right - left)}%` }}
        title={`P10 ${fmtInt(range.p10)} → P90 ${fmtInt(range.p90)} ${range.unit}`}
      />
      <div
        className="absolute top-1/2 h-5 w-[2px] -translate-y-1/2 rounded bg-[var(--primary)]"
        style={{ left: `${median}%` }}
        title={`P50 ${fmtInt(range.p50)} ${range.unit}`}
      />
    </div>
  );
}

/**
 * The demo moment (contract v0.2): the interval BEFORE (original extraction)
 * vs AFTER answering questions. Two whiskers on one shared scale, plus the
 * range-shrink indicator and the remaining-unknowns count.
 */
export function RangeCompare({
  before,
  after,
  unknownCount,
  busy = false,
}: {
  before: EstimateRange;
  after: EstimateRange;
  unknownCount: number;
  busy?: boolean;
}) {
  const beforeWidth = Math.max(1, before.p90 - before.p10);
  const afterWidth = Math.max(1, after.p90 - after.p10);
  const rangeChangePct = ((afterWidth - beforeWidth) / beforeWidth) * 100;
  const p50Delta = after.p50 - before.p50;
  const domainMax = Math.max(before.p90, after.p90, after.p50, before.p50) * 1.08;

  const unit = after.unit || before.unit || "days";

  return (
    <div className="panel-2 space-y-2 p-3" aria-live="polite">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="text-[11px] uppercase tracking-[0.1em] text-[var(--dim)]">
          Interval refinement — before vs after answers
        </div>
        <div className="flex flex-wrap items-center gap-1.5">
          {rangeChangePct <= -0.5 ? (
            <span
              className="chip chip-ok num"
              title={`P90 − P10 shrank from ${fmtInt(beforeWidth)} to ${fmtInt(afterWidth)} ${unit}`}
            >
              range −{Math.abs(rangeChangePct).toFixed(0)}%
            </span>
          ) : rangeChangePct >= 0.5 ? (
            <span
              className="chip chip-unknown num"
              title={`P90 − P10 widened from ${fmtInt(beforeWidth)} to ${fmtInt(afterWidth)} ${unit} — the answer added scope`}
            >
              range +{rangeChangePct.toFixed(0)}%
            </span>
          ) : (
            <span className="chip chip-off num">range unchanged</span>
          )}
          {p50Delta !== 0 && (
            <span
              className={`chip num ${p50Delta > 0 ? "chip-unknown" : "chip-info"}`}
              title="Shift of the median (P50) after applying the answers"
            >
              P50 {p50Delta > 0 ? "+" : "−"}
              {fmtInt(Math.abs(p50Delta))} {unit}
            </span>
          )}
          {unknownCount > 0 ? (
            <span
              className="chip chip-unknown"
              title="Features still unknown; the Monte-Carlo interval samples them from history"
            >
              {unknownCount} unknown{unknownCount === 1 ? "" : "s"} left
            </span>
          ) : (
            <span className="chip chip-ok" title="Every feature resolved — the estimate collapses to a point estimate">
              all features known
            </span>
          )}
          {busy && (
            <span className="chip chip-info" role="status">
              re-running estimate…
            </span>
          )}
        </div>
      </div>

      <div className="grid grid-cols-[54px_minmax(0,1fr)_auto] items-center gap-x-3 gap-y-1.5">
        <span className="text-[10px] uppercase tracking-wider text-[var(--faint)]">
          Before
        </span>
        <Whisker range={before} domainMax={domainMax} tone="before" />
        <span className="num whitespace-nowrap text-[11px] text-[var(--dim)]">
          {fmtInt(before.p10)}–{fmtInt(before.p90)}{" "}
          <span className="text-[var(--faint)]">(P50 {fmtInt(before.p50)})</span>
        </span>

        <span className="text-[10px] uppercase tracking-wider text-[var(--cyan)]">
          After
        </span>
        <Whisker range={after} domainMax={domainMax} tone="after" />
        <span className="num whitespace-nowrap text-[11px] text-[var(--cyan)]">
          {fmtInt(after.p10)}–{fmtInt(after.p90)}{" "}
          <span className="text-[var(--faint)]">(P50 {fmtInt(after.p50)})</span>
        </span>
      </div>

      <p className="text-[10.5px] leading-4 text-[var(--faint)]">
        <span className="inline-block h-2 w-3 rounded-full border border-[var(--hairline-strong)] bg-[var(--surface-3)] align-middle" />{" "}
        original &nbsp;·&nbsp;{" "}
        <span className="inline-block h-2 w-3 rounded-full border border-[var(--primary)] bg-[rgba(94,106,210,0.25)] align-middle" />{" "}
        refined &nbsp;·&nbsp;{" "}
        <span className="inline-block h-2.5 w-[2px] rounded bg-[var(--primary)] align-middle" />{" "}
        P50. The lavender tick is the median; answer-refinement re-calls{" "}
        <span className="num">POST /api/estimate</span> with{" "}
        <span className="num">answers</span> and stores nothing.{" "}
        <Term term="Monte Carlo" tip={GLOSSARY.mc}>
          why does it widen?
        </Term>
      </p>
    </div>
  );
}
