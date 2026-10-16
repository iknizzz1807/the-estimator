"use client";

import { GLOSSARY, Term } from "./Tooltip";

const LONG_EMAIL_CHARS = 10000;

/**
 * Email textarea with pre-flight validation (spec §9): empty → error,
 * >10,000 chars → amber warning but allowed. Ctrl/Cmd+Enter runs.
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
    <div>
      <div className="mb-1.5 flex items-end justify-between gap-3">
        <label
          htmlFor="email-input"
          className="text-xs uppercase tracking-[0.1em] text-[var(--dim)]"
        >
          Client email / RFP
        </label>
        <span className="num text-[11px] text-[var(--faint)]">
          {value.length.toLocaleString("en-US")} chars
        </span>
      </div>
      <textarea
        id="email-input"
        className="textarea"
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
      <div className="mt-1 flex flex-wrap items-center justify-between gap-2 text-[11px] text-[var(--faint)]">
        <span>
          <Term term="Extraction" tip={GLOSSARY.provider}>
            The extractor
          </Term>{" "}
          only reads — the P10/P50/P90 comes from statistics.{" "}
          <span className="num">Ctrl/⌘+Enter</span> runs.
        </span>
        {tooLong && (
          <span className="text-[var(--amber)]">
            Long email (&gt;{LONG_EMAIL_CHARS.toLocaleString("en-US")} chars) —
            results may be less accurate.
          </span>
        )}
      </div>

      {validationError && (
        <div className="banner banner-amber mt-2" role="alert">
          <span aria-hidden>⚠</span>
          <span>{validationError}</span>
        </div>
      )}
    </div>
  );
}
