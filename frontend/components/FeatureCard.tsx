"use client";

import type { Finding } from "@/lib/types";
import {
  FEATURE_GROUPS,
  FEATURES,
  GROUP_LABELS,
  featureDefinition,
  featureLabel,
} from "@/lib/features";
import { ConfidenceBar } from "./ui";
import { Term } from "./Tooltip";

function StatusIcon({ value }: { value: Finding["value"] }) {
  if (value === 1) return <span title="Present in the email">✅</span>;
  if (value === 0) return <span title="Absent / explicitly out of scope">❌</span>;
  return <span title="Not mentioned — unknown">⚠️</span>;
}

const STATUS_LABEL: Record<string, string> = {
  "1": "present",
  "0": "absent",
  unknown: "unknown",
};

export function FeatureCard({ finding }: { finding: Finding }) {
  const status =
    finding.value === null ? "unknown" : String(finding.value);
  const border =
    finding.value === null
      ? "border-[rgba(251,191,36,0.35)]"
      : finding.value === 1
        ? "border-[rgba(163,230,53,0.28)]"
        : "border-[var(--border)]";

  return (
    <div className={`panel-2 border ${border} p-3`}>
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-2">
          <StatusIcon value={finding.value} />
          <span className="text-sm font-medium leading-tight">
            {featureLabel(finding.name)}
          </span>
        </div>
        <span className="num text-[10px] uppercase tracking-[0.08em] text-[var(--faint)]">
          {STATUS_LABEL[finding.value === null ? "unknown" : status]}
        </span>
      </div>

      <div className="mt-1.5 text-[11px] leading-4 text-[var(--faint)]">
        <Term term={featureLabel(finding.name)} tip={featureDefinition(finding.name)}>
          {featureDefinition(finding.name)}
        </Term>
      </div>

      <div className="mt-2">
        <ConfidenceBar value={finding.confidence} />
      </div>

      {finding.evidence_quote ? (
        <blockquote className="mt-2 border-l-2 border-[var(--border-strong)] pl-2 text-[11px] italic leading-4 text-[var(--dim)]">
          “{finding.evidence_quote}”
        </blockquote>
      ) : (
        <p className="mt-2 text-[11px] leading-4 text-[var(--faint)]">
          {finding.value === null
            ? "No evidence found — worth asking."
            : "No quote captured — flagged for review."}
        </p>
      )}
    </div>
  );
}

/** All 15 features, grouped by the 5 complexity groups from features.py. */
export function FeatureGrid({ findings }: { findings: Finding[] }) {
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

  return (
    <div className="space-y-4">
      <div className="num text-xs text-[var(--faint)]">
        {presentCount}/15 present · {unknownCount} unknown
      </div>
      {Object.entries(FEATURE_GROUPS).map(([group, names]) => {
        const groupFindings = merged.filter((f) => names.includes(f.name));
        const present = groupFindings.filter((f) => f.value === 1).length;
        return (
          <div key={group}>
            <div className="mb-2 flex items-center gap-3">
              <h3 className="text-[11px] font-semibold uppercase tracking-[0.14em] text-[var(--dim)]">
                {GROUP_LABELS[group]}
              </h3>
              <span className="num text-[10.5px] text-[var(--faint)]">
                {present}/{names.length} present
              </span>
              <span className="h-px flex-1 bg-[var(--border)]" />
            </div>
            <div className="grid gap-2.5 sm:grid-cols-2 xl:grid-cols-3">
              {groupFindings.map((finding) => (
                <FeatureCard key={finding.name} finding={finding} />
              ))}
            </div>
          </div>
        );
      })}
    </div>
  );
}
