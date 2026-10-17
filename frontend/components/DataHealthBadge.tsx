"use client";

import { api } from "@/lib/api";
import { useAsyncData } from "@/lib/hooks";
import { Spinner } from "./ui";
import { GLOSSARY, Term } from "./Tooltip";

/**
 * Sidebar data-health chip: projects count, model state and the extraction
 * provider from GET /api/health. Follows Linear design guidelines with subtle
 * hairline panel framing and semantic success/warning indicators.
 */
export default function DataHealthBadge() {
  const { data, loading, error, reload } = useAsyncData(() => api.health());

  if (loading && !data) {
    return (
      <div className="mx-3 mb-2 flex items-center gap-2 rounded-lg border border-[var(--hairline)] bg-[var(--surface-1)] px-3 py-2.5 text-xs text-[var(--ink-tertiary)]">
        <Spinner className="h-3 w-3" /> Checking data health…
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="mx-3 mb-2 rounded-lg border border-[rgba(217,119,6,0.35)] bg-[rgba(217,119,6,0.06)] p-3 text-xs text-[#fde68a]">
        <div className="font-medium text-xs">Health unknown</div>
        <div className="mt-0.5 text-[11px] opacity-90">{error ?? "No response from /api/health"}</div>
        <button type="button" className="btn btn-secondary mt-2 w-full py-1 text-xs" onClick={reload}>
          Retry
        </button>
      </div>
    );
  }

  const provider = data.llm_provider.toLowerCase();
  const providerTone =
    provider === "stub"
      ? "border-[rgba(217,119,6,0.35)] bg-[rgba(217,119,6,0.1)] text-[#fde68a]"
      : provider === "gemini" || provider === "openai" || provider === "claude"
        ? "border-[rgba(39,166,68,0.35)] bg-[rgba(39,166,68,0.1)] text-[#4ade80]"
        : "border-[var(--hairline)] bg-[var(--surface-2)] text-[var(--ink-subtle)]";
  const providerLabel =
    provider === "stub" ? "stub · offline extractor" : provider;

  return (
    <div className="mx-3 mb-2 rounded-lg border border-[var(--hairline)] bg-[var(--surface-1)] p-3 text-xs">
      <div className="flex items-center justify-between gap-2">
        <span className="text-[10px] font-semibold uppercase tracking-[0.08em] text-[var(--ink-subtle)]">
          Data health
        </span>
        <span
          className={`h-2 w-2 rounded-full ${
            data.status === "ok"
              ? "bg-[var(--success)] shadow-[0_0_6px_rgba(39,166,68,0.4)]"
              : "bg-[var(--warning)] shadow-[0_0_6px_rgba(217,119,6,0.4)]"
          }`}
          title={`status: ${data.status}`}
        />
      </div>
      <div className="num mt-1.5 text-xs font-medium text-[var(--ink)] tabular-nums">
        {data.projects_count} projects
        <span className="font-normal text-[var(--ink-tertiary)]">
          {" "}· {data.model_loaded ? "model loaded" : "no model"}
        </span>
      </div>
      <div className="mt-1.5">
        <span
          className={`num inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-medium ${providerTone}`}
          title={GLOSSARY.provider}
        >
          {providerLabel}
        </span>
      </div>
      <div className="mt-2 text-[10px] leading-4 text-[var(--ink-tertiary)]">
        <Term term="Provider" tip={GLOSSARY.provider}>
          what reads the emails
        </Term>
      </div>
    </div>
  );
}
