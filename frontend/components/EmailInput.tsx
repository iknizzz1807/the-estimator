"use client";

import { GLOSSARY, Term } from "./Tooltip";

const LONG_EMAIL_CHARS = 10000;

/**
 * Email textarea with pre-flight validation (spec §9): empty → error,
 * >10,000 chars → amber warning but allowed. Ctrl/Cmd+Enter runs.
 * Styled to Linear design language: Surface-1 background (#0f1011),
 * hairline border (#23252a), and lavender focus ring (#5e69d1).
 */
export function EmailInput({
  value,
  onChange,
  onSubmit,
  running,
  disabled,
  validationError,
}: {
  value: string;
  onChange: (value: string) => void;
  onSubmit: () => void;
  running: boolean;
  disabled?: boolean;
  validationError?: string | null;
}) {
  const tooLong = value.length > LONG_EMAIL_CHARS;

  return (
    <div className="space-y-2">
      <div className="flex items-end justify-between gap-3">
        <label
          htmlFor="email-input"
          className="text-[11px] font-medium uppercase tracking-[0.1em] text-[#8a8f98]"
        >
          Client email / RFP
        </label>
        <span className="font-mono text-[11px] tabular-nums text-[#62666d]">
          {value.length.toLocaleString("en-US")} chars
        </span>
      </div>

      <div className="relative rounded-lg">
        <textarea
          id="email-input"
          className="w-full min-h-[160px] resize-y rounded-lg border border-[#23252a] bg-[#0f1011] px-3.5 py-3 font-mono text-[13px] leading-relaxed text-[#f7f8f8] placeholder-[#62666d] transition-colors focus:border-[#5e6ad2] focus:outline-none focus:ring-1 focus:ring-[#5e69d1] disabled:cursor-not-allowed disabled:opacity-50"
          placeholder={
            "Paste the client email here…\n\nExample: “We are building an insurance claims portal and need SSO with the customer's identity provider, GDPR compliance, and a data migration from our legacy system.”"
          }
          value={value}
          disabled={disabled}
          onChange={(event) => onChange(event.target.value)}
          onKeyDown={(event) => {
            if ((event.metaKey || event.ctrlKey) && event.key === "Enter") {
              event.preventDefault();
              if (!running) onSubmit();
            }
          }}
        />
      </div>

      <div className="flex flex-wrap items-center justify-between gap-2 text-[11px] text-[#8a8f98]">
        <span className="flex items-center gap-1.5">
          <span>
            <Term term="Extraction" tip={GLOSSARY.provider}>
              The extractor
            </Term>{" "}
            only reads — the P10/P50/P90 comes from statistics.
          </span>
          <kbd className="inline-flex items-center rounded border border-[#23252a] bg-[#141516] px-1.5 py-0.5 font-mono text-[10px] text-[#d0d6e0]">
            Ctrl/⌘+Enter
          </kbd>
          <span>runs.</span>
        </span>

        {tooLong && (
          <span className="inline-flex items-center gap-1 text-[#f59e0b]">
            <span aria-hidden="true">⚠</span>
            <span>
              Long email (&gt;{LONG_EMAIL_CHARS.toLocaleString("en-US")} chars) — results may be less accurate.
            </span>
          </span>
        )}
      </div>

      {validationError && (
        <div
          className="flex items-center gap-2 rounded-lg border border-[rgba(245,158,11,0.3)] bg-[rgba(245,158,11,0.08)] px-3 py-2 text-xs text-[#f59e0b]"
          role="alert"
        >
          <span aria-hidden="true" className="shrink-0 text-sm">⚠</span>
          <span>{validationError}</span>
        </div>
      )}
    </div>
  );
}
