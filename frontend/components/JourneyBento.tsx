"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import { storeEstimate, storePrefillEmail } from "@/lib/session";
import {
  JOURNEY_MILESTONES,
  getJourneyState,
  markStepComplete,
  queueJourneyAction,
  type JourneyMilestone,
  type JourneyState,
} from "@/lib/journey";
import { Spinner } from "./ui";

export function JourneyBento() {
  const router = useRouter();
  const [state, setState] = useState<JourneyState>(getJourneyState());
  const [loadingStepId, setLoadingStepId] = useState<string | null>(null);

  useEffect(() => {
    setState(getJourneyState());
    const handleStateChange = (event: Event) => {
      const custom = event as CustomEvent<JourneyState>;
      if (custom.detail) setState(custom.detail);
    };
    window.addEventListener("estimator:journey-state-changed", handleStateChange);
    return () => {
      window.removeEventListener("estimator:journey-state-changed", handleStateChange);
    };
  }, []);

  const runMilestone = async (milestone: JourneyMilestone) => {
    setLoadingStepId(milestone.id);
    try {
      if (milestone.id === "scenario_stream") {
        // Load Scenario A (Fintech) directly
        const estimate = await api.loadScenario("A");
        const scenarios = await api.scenarios();
        const scA = scenarios.find((s) => s.id === "A");
        storeEstimate({ estimate, scenarioTitle: "Fintech payment + PCI" });
        if (scA?.email_text) storePrefillEmail(scA.email_text);
        markStepComplete("scenario_stream");
        router.push("/estimate?from=scenario");
      } else if (milestone.id === "voi_shrink") {
        queueJourneyAction({ type: "voi_shrink" });
        router.push("/estimate?journey=voi");
      } else if (milestone.id === "codebase_friction") {
        queueJourneyAction({ type: "codebase_friction" });
        router.push("/estimate?journey=codebase");
      } else if (milestone.id === "proof_replay") {
        queueJourneyAction({ type: "proof_replay" });
        router.push("/proof?journey=replay");
      }
    } catch (err) {
      console.error("Failed to run journey milestone", err);
      // Fallback navigation
      router.push(milestone.targetRoute);
    } finally {
      setLoadingStepId(null);
    }
  };

  const completedCount = Object.keys(state.completed).filter((k) => state.completed[k]).length;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[var(--hairline)] pb-3">
        <div>
          <div className="flex items-center gap-2">
            <span className="h-2 w-2 rounded-full bg-[var(--primary)] animate-pulse" />
            <h2 className="text-xs font-semibold uppercase tracking-[0.12em] text-[var(--ink-muted)]">
              Interactive Evaluation Track
            </h2>
          </div>
          <p className="mt-0.5 text-xs text-[var(--ink-subtle)]">
            4 executable milestones proving The Estimator is a calibrated statistics engine, not an LLM wrapper.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <span className="num text-xs font-mono text-[var(--ink-muted)]">
            {completedCount}/{JOURNEY_MILESTONES.length} Completed
          </span>
          <div className="h-1.5 w-24 overflow-hidden rounded-full bg-[var(--surface-3)] border border-[var(--hairline)]">
            <div
              className="h-full bg-[var(--primary)] transition-all duration-300"
              style={{ width: `${(completedCount / JOURNEY_MILESTONES.length) * 100}%` }}
            />
          </div>
        </div>
      </div>

      <div className="grid gap-3.5 sm:grid-cols-2 xl:grid-cols-4">
        {JOURNEY_MILESTONES.map((m) => {
          const isDone = Boolean(state.completed[m.id]);
          const isLoading = loadingStepId === m.id;

          return (
            <div
              key={m.id}
              className={`group relative flex flex-col justify-between rounded-xl border p-4.5 transition-all duration-200 ${
                isDone
                  ? "border-[rgba(39,166,68,0.3)] bg-[var(--surface-1)] shadow-[0_4px_20px_rgba(0,0,0,0.5)]"
                  : "border-[var(--hairline)] bg-[var(--surface-1)] hover:border-[var(--hairline-strong)] hover:bg-[var(--surface-2)]"
              }`}
            >
              <div>
                <div className="flex items-center justify-between gap-2">
                  <span className="num font-mono text-xs font-semibold tracking-wider text-[var(--primary)]">
                    {m.number}
                  </span>
                  {isDone ? (
                    <span className="inline-flex items-center gap-1 rounded-full border border-[rgba(39,166,68,0.3)] bg-[rgba(39,166,68,0.1)] px-2 py-0.5 text-[10px] font-medium text-[var(--success)]">
                      ✓ Done
                    </span>
                  ) : (
                    <span className="rounded-full border border-[var(--hairline)] bg-[var(--surface-3)] px-2 py-0.5 text-[10px] font-mono text-[var(--ink-tertiary)]">
                      {m.keyMetric}
                    </span>
                  )}
                </div>

                <h3 className="mt-2 text-sm font-semibold tracking-tight text-[var(--ink)]">
                  {m.title}
                </h3>
                <p className="mt-1 text-xs leading-relaxed text-[var(--ink-subtle)]">
                  {m.description}
                </p>

                <div className="mt-3 rounded-lg border border-[var(--hairline)] bg-[var(--canvas)] p-2.5">
                  <div className="text-[10px] font-semibold uppercase tracking-wider text-[var(--primary)]">
                    Aha! Moment
                  </div>
                  <div className="mt-0.5 text-[11px] leading-relaxed text-[var(--ink-muted)]">
                    {m.ahaMoment}
                  </div>
                </div>
              </div>

              <div className="mt-4 pt-3 border-t border-[var(--hairline)]">
                <button
                  type="button"
                  disabled={isLoading}
                  onClick={() => runMilestone(m)}
                  className={`btn w-full justify-between text-xs font-medium ${
                    isDone
                      ? "border-[var(--hairline)] bg-[var(--surface-2)] text-[var(--ink-muted)] hover:border-[var(--primary)] hover:text-[var(--ink)]"
                      : "btn-primary"
                  }`}
                >
                  <span>{isLoading ? "Executing…" : m.actionLabel}</span>
                  {isLoading ? <Spinner className="h-3.5 w-3.5" /> : <span>→</span>}
                </button>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
