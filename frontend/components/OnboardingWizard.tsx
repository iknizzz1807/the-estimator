"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { api } from "@/lib/api";
import { storeEstimate, storePrefillEmail } from "@/lib/session";
import { useAsyncData } from "@/lib/hooks";
import { ImportCSVModal } from "./ImportCSVModal";
import { ErrorState, SkeletonLines, Spinner } from "./ui";

const STEP_ICONS = ["1", "2", "3", "4", "5"];

/**
 * The four onboarding paths (spec §3.1). Judges must reach a populated
 * Estimate view in one click → "Load Sample Data" buttons.
 */
export default function OnboardingWizard() {
  const router = useRouter();
  const scenarios = useAsyncData(() => api.scenarios());
  const [loadingId, setLoadingId] = useState<string | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [showImport, setShowImport] = useState(false);

  const loadScenario = async (id: string, emailText: string) => {
    setLoadingId(id);
    setLoadError(null);
    try {
      const estimate = await api.loadScenario(id);
      storeEstimate({ estimate, scenarioTitle: id });
      storePrefillEmail(emailText);
      router.push("/estimate?from=scenario");
    } catch (err) {
      setLoadError(
        err instanceof Error ? err.message : "Could not load the scenario"
      );
      setLoadingId(null);
    }
  };

  return (
    <div className="grid gap-4 lg:grid-cols-2">
      {/* (a) Load Sample Data — 1-click demo path */}
      <section className="panel p-5" aria-labelledby="card-samples">
        <div className="flex items-center justify-between">
          <h2 id="card-samples" className="text-sm font-semibold uppercase tracking-[0.12em] text-[var(--cyan)]">
            ▸ Load sample data
          </h2>
          <span className="chip chip-info">1 click → results</span>
        </div>
        <p className="mt-2 text-xs leading-5 text-[var(--dim)]">
          Three pre-built RFPs. One click runs the full pipeline: extract 15
          features, find similar past projects, estimate the range and rank the
          questions.
        </p>

        <div className="mt-3 space-y-2">
          {scenarios.loading && <SkeletonLines lines={3} />}

          {scenarios.error && !scenarios.loading && (
            <ErrorState
              title="Could not load sample scenarios"
              message={scenarios.error}
              onRetry={scenarios.reload}
              hint="The backend exposes GET /api/scenarios — start it with scripts/run_api.sh."
            />
          )}

          {scenarios.data?.map((scenario) => (
            <button
              key={scenario.id}
              type="button"
              className="panel-2 group flex w-full items-center justify-between gap-3 px-4 py-3 text-left transition hover:border-[rgba(34,211,238,0.45)]"
              disabled={loadingId !== null}
              onClick={() => loadScenario(scenario.id, scenario.email_text)}
            >
              <span className="min-w-0">
                <span className="block text-sm font-medium text-[var(--text)]">
                  {scenario.title}
                </span>
                <span className="mt-0.5 block truncate text-xs text-[var(--faint)]">
                  {scenario.notes ?? `${scenario.email_text.length} characters`}
                </span>
              </span>
              <span className="shrink-0 text-[var(--cyan)]">
                {loadingId === scenario.id ? (
                  <Spinner className="h-4 w-4" />
                ) : (
                  <span className="text-lg transition group-hover:translate-x-0.5">
                    →
                  </span>
                )}
              </span>
            </button>
          ))}
        </div>

        {loadError && (
          <div className="banner banner-red mt-3" role="alert">
            <span aria-hidden>✕</span>
            <div className="text-xs">
              <div className="font-medium">Could not load the scenario</div>
              <div className="num opacity-90">{loadError}</div>
              <div className="opacity-80">Check the backend, then click a scenario again.</div>
            </div>
          </div>
        )}
      </section>

      {/* (b) Import CSV */}
      <section className="panel flex flex-col p-5" aria-labelledby="card-import">
        <h2 id="card-import" className="text-sm font-semibold uppercase tracking-[0.12em] text-[var(--cyan)]">
          ▸ Import your own history
        </h2>
        <p className="mt-2 flex-1 text-xs leading-5 text-[var(--dim)]">
          Bring {""}
          <span className="text-[var(--text)]">50–60 finished projects</span> and
          the model calibrates on your data instead of industry baselines. CSV
          only (Jira/Harvest export works); invalid rows are reported, not
          silently dropped. New rows are training samples immediately.
        </p>
        <button
          type="button"
          className="btn btn-primary mt-4 self-start"
          onClick={() => setShowImport(true)}
        >
          Import CSV…
        </button>
      </section>

      {/* (c) Cold start */}
      <section className="panel flex flex-col p-5" aria-labelledby="card-cold">
        <h2 id="card-cold" className="text-sm font-semibold uppercase tracking-[0.12em] text-[var(--amber)]">
          ▸ Cold start (no history)
        </h2>
        <p className="mt-2 flex-1 text-xs leading-5 text-[var(--dim)]">
          No historical data yet? The system still helps today: it standardizes
          the RFP, detects missing information and drafts the questions to ask —
          using documented industry multipliers with a deliberately{" "}
          <span className="text-[var(--text)]">wider interval</span> until enough
          projects accumulate.
        </p>
        <Link
          href="/estimate?cold=1"
          className="btn btn-warn mt-4 self-start"
        >
          Try a cold-start estimate →
        </Link>
      </section>

      {/* (d) How it works */}
      <section className="panel p-5" aria-labelledby="card-how">
        <h2 id="card-how" className="text-sm font-semibold uppercase tracking-[0.12em] text-[var(--lime)]">
          ▸ How it works
        </h2>
        <ol className="mt-3 space-y-1.5 text-xs text-[var(--dim)]">
          {[
            ["Paste the client email", "any length, EN or VI"],
            ["Extract 15 features", "with verbatim evidence quotes"],
            ["Estimate with math", "Ridge + conformal → P10/P50/P90, ~80% coverage"],
            ["Rank the questions", "by Value of Information (impact in days)"],
            ["Learn from actuals", "coefficients update; accuracy becomes visible"],
          ].map(([title, detail], index) => (
            <li key={title} className="flex items-start gap-2.5">
              <span className="num mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded border border-[var(--border-strong)] text-[10px] text-[var(--cyan)]">
                {STEP_ICONS[index]}
              </span>
              <span>
                <span className="text-[var(--text)]">{title}</span>
                <span className="text-[var(--faint)]"> — {detail}</span>
              </span>
            </li>
          ))}
        </ol>
        <p className="mt-3 border-t border-[var(--border)] pt-2 text-[11px] text-[var(--faint)]">
          No chat interface — every screen is a form, table, chart or card. The
          LLM only reads; the numbers come from statistics you can audit.
        </p>
      </section>

      {showImport && (
        <ImportCSVModal
          onClose={() => setShowImport(false)}
          onViewHistory={() => {
            setShowImport(false);
            router.push("/history");
          }}
        />
      )}
    </div>
  );
}
