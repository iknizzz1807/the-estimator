"use client";

import { api } from "@/lib/api";
import { useAsyncData } from "@/lib/hooks";
import { Spinner } from "./ui";
import { GLOSSARY, Term } from "./Tooltip";

/**
 * Sidebar data-health chip: projects count, model state and the extraction
 * provider from GET /api/health. stub (no API key) is amber and labelled
 * "offline extractor" per docs/DECISIONS.md D2.
 */
export default function DataHealthBadge() {
  const { data, loading, error, reload } = useAsyncData(() => api.health());

  if (loading && !data) {
    return (
      <div className="mx-3 mb-2 flex items-center gap-2 rounded-lg border border-[var(--border)] px-3 py-2 text-xs text-[var(--faint)]">
        <Spinner className="h-3 w-3" /> Checking data health…
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="mx-3 mb-2 rounded-lg border border-[rgba(251,191,36,0.4)] bg-[rgba(251,191,36,0.06)] px-3 py-2 text-xs text-[#fde68a]">
        <div className="font-medium">Health unknown</div>
        <div className="mt-0.5 opacity-90">{error ?? "No response from /api/health"}</div>
        <button type="button" className="btn mt-1.5 w-full" onClick={reload}>
          Retry
        </button>
      </div>
    );
  }

  const provider = data.llm_provider.toLowerCase();
  const providerTone =
    provider === "stub"
      ? "border-[rgba(251,191,36,0.45)] bg-[rgba(251,191,36,0.08)] text-[#fde68a]"
      : provider === "gemini" || provider === "openai" || provider === "claude"
        ? "border-[rgba(163,230,53,0.45)] bg-[rgba(163,230,53,0.08)] text-[#d9f99d]"
        : "border-[var(--border)] text-[var(--dim)]";
  const providerLabel =
    provider === "stub" ? "stub · offline extractor" : provider;

  return (
    <div className="mx-3 mb-2 rounded-lg border border-[var(--border)] px-3 py-2 text-xs">
      <div className="flex items-center justify-between gap-2">
        <span className="uppercase tracking-[0.1em] text-[var(--faint)]">Data health</span>
        <span
          className={`h-2 w-2 rounded-full ${
            data.status === "ok" ? "bg-[var(--lime)]" : "bg-[var(--amber)]"
          }`}
          title={`status: ${data.status}`}
        />
      </div>
      <div className="num mt-1.5 text-[var(--text)]">
        {data.projects_count} projects
        <span className="text-[var(--faint)]"> · {data.model_loaded ? "model loaded" : "no model"}</span>
      </div>
      <div className="mt-1.5">
        <span
          className={`num inline-flex items-center rounded-full border px-2 py-0.5 text-[10.5px] ${providerTone}`}
          title={GLOSSARY.provider}
        >
          {providerLabel}
        </span>
      </div>
      <div className="mt-1.5 text-[10px] leading-4 text-[var(--faint)]">
        <Term term="Provider" tip={GLOSSARY.provider}>
          what reads the emails
        </Term>
      </div>
    </div>
  );
}
