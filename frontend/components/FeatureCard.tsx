"use client";

import type { AnswersMap, Finding } from "@/lib/types";
import {
  FEATURE_GROUPS,
  FEATURES,
  GROUP_LABELS,
  featureDefinition,
  featureLabel,
} from "@/lib/features";
import { Term } from "./Tooltip";

function StatusBadge({ value }: { value: Finding["value"] }) {
  if (value === 1) {
    return (
      <span
        className="inline-flex items-center gap-1.5 rounded-full border border-[rgba(39,166,68,0.3)] bg-[rgba(39,166,68,0.1)] px-2 py-0.5 text-[10px] font-medium tracking-wide text-[#27a644]"
        title="Detected in the email"
      >
        <span className="h-1.5 w-1.5 rounded-full bg-[#27a644]" />
        Present
      </span>
    );
  }
  if (value === 0) {
    return (
      <span
        className="inline-flex items-center gap-1.5 rounded-full border border-[#23252a] bg-[#141516] px-2 py-0.5 text-[10px] font-medium tracking-wide text-[#8a8f98]"
        title="Explicitly absent or out of scope"
      >
        <span className="h-1.5 w-1.5 rounded-full bg-[#62666d]" />
        Absent
      </span>
    );
  }
  return (
    <span
      className="inline-flex items-center gap-1.5 rounded-full border border-[rgba(245,158,11,0.3)] bg-[rgba(245,158,11,0.1)] px-2 py-0.5 text-[10px] font-medium tracking-wide text-[#f59e0b]"
      title="Not mentioned in the email — unknown"
    >
      <span className="h-1.5 w-1.5 rounded-full bg-[#f59e0b]" />
      Unknown
    </span>
  );
}

function FeatureConfidence({ confidence }: { confidence: number | null }) {
  if (confidence === null || confidence === undefined) return null;
  const pct = Math.round(confidence * 100);
  const barColor =
    pct >= 75 ? "bg-[#27a644]" : pct >= 45 ? "bg-[#5e6ad2]" : "bg-[#f59e0b]";

  return (
    <div
      className="flex items-center justify-between gap-2"
      title={`Extraction confidence ${pct}%`}
    >
      <span className="text-[10px] uppercase tracking-wider text-[#62666d]">
        Confidence
      </span>
      <div className="flex items-center gap-2">
        <div className="h-1 w-14 overflow-hidden rounded-full bg-[#18191a]">
          <div className={`h-full ${barColor}`} style={{ width: `${pct}%` }} />
        </div>
        <span className="font-mono text-[10px] tabular-nums text-[#8a8f98]">
          {pct}%
        </span>
      </div>
    </div>
  );
}

function originalLabel(value: Finding["value"]): string {
  if (value === 1) return "Present";
  if (value === 0) return "Absent";
  return "Unknown";
}

function OverrideButtons({
  feature,
  chosen,
  onAnswer,
  busy,
}: {
  feature: string;
  chosen?: 0 | 1;
  onAnswer?: (feature: string, value: 0 | 1) => void;
  busy?: boolean;
}) {
  if (!onAnswer) return null;
  return (
    <div
      className="flex items-center gap-1"
      role="group"
      aria-label={`Override ${featureLabel(feature)}`}
    >
      <button
        type="button"
        disabled={busy}
        aria-pressed={chosen === 1}
        title="Override: this capability IS in scope (your assertion, not the extractor's)."
        className={`rounded-full px-2.5 py-0.5 font-mono text-xs font-medium transition-colors ${
          chosen === 1
            ? "border border-[rgba(94,106,210,0.6)] bg-[rgba(94,106,210,0.18)] text-[#828fff]"
            : "border border-[#23252a] bg-[#141516] text-[#8a8f98] hover:border-[#34343a] hover:text-[#f7f8f8]"
        } disabled:cursor-not-allowed disabled:opacity-50`}
        onClick={() => onAnswer(feature, 1)}
      >
        Có
      </button>
      <button
        type="button"
        disabled={busy}
        aria-pressed={chosen === 0}
        title="Override: this capability is NOT needed (your assertion, not the extractor's)."
        className={`rounded-full px-2.5 py-0.5 font-mono text-xs font-medium transition-colors ${
          chosen === 0
            ? "border border-[rgba(245,158,11,0.5)] bg-[rgba(245,158,11,0.15)] text-[#f59e0b]"
            : "border border-[#23252a] bg-[#141516] text-[#8a8f98] hover:border-[#34343a] hover:text-[#f7f8f8]"
        } disabled:cursor-not-allowed disabled:opacity-50`}
        onClick={() => onAnswer(feature, 0)}
      >
        Không
      </button>
    </div>
  );
}

export function FeatureCard({
  finding,
  original,
  answer,
  onAnswer,
  busy = false,
}: {
  finding: Finding;
  /**
   * The ORIGINAL extraction value (from the un-refined response). Shown whenever
   * the user overrode the card, so an override never hides what the LLM said —
   * the audit trail stays intact (DECISIONS D29).
   */
  original?: Finding["value"];
  /** The user's override for this feature (undefined = not overridden). */
  answer?: 0 | 1;
  onAnswer?: (feature: string, value: 0 | 1) => void;
  busy?: boolean;
}) {
  const overridden = answer !== undefined;
  return (
    <div
      className={`group flex flex-col justify-between rounded-lg border bg-[#0f1011] p-3.5 transition-colors hover:bg-[#141516] ${
        overridden ? "border-[rgba(94,106,210,0.45)]" : "border-[#23252a] hover:border-[#34343a]"
      }`}
    >
      <div>
        <div className="flex items-start justify-between gap-2">
          <h4 className="text-[13px] font-medium leading-snug text-[#f7f8f8] group-hover:text-white">
            {featureLabel(finding.name)}
          </h4>
          <div className="flex shrink-0 items-center gap-1.5">
            {overridden && (
              <span
                className="inline-flex items-center gap-1 rounded-full border border-[rgba(94,106,210,0.5)] bg-[rgba(94,106,210,0.14)] px-2 py-0.5 text-[10px] font-medium tracking-wide text-[#828fff]"
                title={`You set this; the extractor said ${originalLabel(original ?? null)}.`}
              >
                you set this
              </span>
            )}
            <StatusBadge value={finding.value} />
          </div>
        </div>

        <div className="mt-1 text-[11px] leading-relaxed text-[#8a8f98]">
          <Term term={featureLabel(finding.name)} tip={featureDefinition(finding.name)}>
            <span className="line-clamp-2">{featureDefinition(finding.name)}</span>
          </Term>
        </div>
      </div>

      <div className="mt-3 space-y-2 border-t border-[#23252a]/70 pt-2.5">
        <FeatureConfidence confidence={finding.confidence} />

        {overridden && (
          <p className="text-[11px] leading-relaxed text-[#62666d]">
            Extracted: <span className="text-[#8a8f98]">{originalLabel(original ?? null)}</span> —
            overridden by you. The quote below is still the extractor&apos;s evidence.
          </p>
        )}

        {finding.evidence_quote ? (
          <blockquote className="border-l border-[#34343a] pl-2 text-[11px] italic leading-relaxed text-[#8a8f98] selection:bg-[#5e6ad2]/20">
            “{finding.evidence_quote}”
          </blockquote>
        ) : (
          <p className="text-[11px] leading-relaxed text-[#62666d]">
            {finding.value === null
              ? "No evidence found — flagged as open question."
              : "No quote captured — flagged for review."}
          </p>
        )}

        <div className="flex items-center justify-between gap-2 pt-0.5">
          <span className="text-[10px] uppercase tracking-wider text-[#62666d]">
            Override
          </span>
          <OverrideButtons
            feature={finding.name}
            chosen={answer}
            onAnswer={onAnswer}
            busy={busy}
          />
        </div>
      </div>
    </div>
  );
}

/** All 15 features, grouped by the 5 complexity groups from features.py. */
export function FeatureGrid({
  findings,
  originals = {},
  answers = {},
  onAnswer,
  busy = false,
}: {
  findings: Finding[];
  /** Original extraction values, keyed by feature (shown when overridden). */
  originals?: Record<string, Finding["value"]>;
  /** Accumulated user overrides, keyed by feature. */
  answers?: AnswersMap;
  onAnswer?: (feature: string, value: 0 | 1) => void;
  busy?: boolean;
}) {
  const byName = new Map(findings.map((f) => [f.name, f]));
  const merged: Finding[] = FEATURES.map(
    (name) =>
      byName.get(name) ?? {
        name,
        value: null,
        confidence: 0,
        evidence_quote: null,
      }
  );
  const presentCount = merged.filter((f) => f.value === 1).length;
  const unknownCount = merged.filter((f) => f.value === null).length;
  const overriddenCount = merged.filter((f) => answers[f.name] !== undefined).length;

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between text-xs text-[#8a8f98]">
        <div className="flex items-center gap-2">
          <span className="font-mono tabular-nums text-[#f7f8f8]">
            {presentCount}/15
          </span>
          <span>features detected</span>
          <span className="text-[#62666d]">·</span>
          <span className="font-mono tabular-nums text-[#f59e0b]">
            {unknownCount} unknown
          </span>
          {overriddenCount > 0 && (
            <>
              <span className="text-[#62666d]">·</span>
              <span className="font-mono tabular-nums text-[#828fff]">
                {overriddenCount} you set
              </span>
            </>
          )}
        </div>
      </div>

      {Object.entries(FEATURE_GROUPS).map(([group, names]) => {
        const groupFindings = merged.filter((f) => names.includes(f.name));
        const present = groupFindings.filter((f) => f.value === 1).length;
        return (
          <div key={group} className="space-y-2.5">
            <div className="flex items-center gap-3">
              <h3 className="text-[11px] font-medium uppercase tracking-[0.14em] text-[#8a8f98]">
                {GROUP_LABELS[group]}
              </h3>
              <span className="font-mono text-[10.5px] tabular-nums text-[#62666d]">
                {present}/{names.length} present
              </span>
              <span className="h-px flex-1 bg-[#23252a]" />
            </div>
            <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
              {groupFindings.map((finding) => (
                <FeatureCard
                  key={finding.name}
                  finding={finding}
                  original={originals[finding.name]}
                  answer={answers[finding.name]}
                  onAnswer={onAnswer}
                  busy={busy}
                />
              ))}
            </div>
          </div>
        );
      })}
    </div>
  );
}
