"use client";

import { useEffect, useState } from "react";
import { useRouter, usePathname } from "next/navigation";
import { api } from "@/lib/api";
import { storeEstimate, storePrefillEmail } from "@/lib/session";
import {
  JOURNEY_MILESTONES,
  getJourneyState,
  markStepComplete,
  resetJourney,
  queueJourneyAction,
  type JourneyMilestone,
  type JourneyState,
} from "@/lib/journey";
import { Spinner } from "./ui";

export function JourneyHUD() {
  const router = useRouter();
  const pathname = usePathname();
  const [isOpen, setIsOpen] = useState(false);
  const [state, setState] = useState<JourneyState>(getJourneyState());
  const [selectedMilestone, setSelectedMilestone] = useState<JourneyMilestone>(JOURNEY_MILESTONES[0]);
  const [isExecuting, setIsExecuting] = useState(false);

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

  // Sync selected milestone with current progress
  useEffect(() => {
    const nextIncomplete = JOURNEY_MILESTONES.find((m) => !state.completed[m.id]);
    setSelectedMilestone(nextIncomplete ?? JOURNEY_MILESTONES[0]);
  }, [state.completed]);

  // Global keyboard shortcuts (Ctrl/Cmd + J to toggle HUD, Esc to close)
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "j") {
        e.preventDefault();
        setIsOpen((prev) => !prev);
      } else if (e.key === "Escape" && isOpen) {
        setIsOpen(false);
      } else if (isOpen && ["1", "2", "3", "4"].includes(e.key)) {
        const index = parseInt(e.key, 10) - 1;
        if (JOURNEY_MILESTONES[index]) {
          setSelectedMilestone(JOURNEY_MILESTONES[index]);
        }
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [isOpen]);

  const runMilestone = async (milestone: JourneyMilestone) => {
    setIsExecuting(true);
    try {
      if (milestone.id === "scenario_stream") {
        const estimate = await api.loadScenario("A");
        const scenarios = await api.scenarios();
        const scA = scenarios.find((s) => s.id === "A");
        storeEstimate({ estimate, scenarioTitle: "Fintech payment + PCI" });
        if (scA?.email_text) storePrefillEmail(scA.email_text);
        markStepComplete("scenario_stream");
        setIsOpen(false);
        router.push("/estimate?from=scenario");
      } else if (milestone.id === "voi_shrink") {
        queueJourneyAction({ type: "voi_shrink" });
        setIsOpen(false);
        if (pathname === "/estimate") {
          window.dispatchEvent(new CustomEvent("estimator:journey-action", { detail: { type: "voi_shrink" } }));
        } else {
          router.push("/estimate?journey=voi");
        }
      } else if (milestone.id === "codebase_friction") {
        queueJourneyAction({ type: "codebase_friction" });
        setIsOpen(false);
        if (pathname === "/estimate") {
          window.dispatchEvent(new CustomEvent("estimator:journey-action", { detail: { type: "codebase_friction" } }));
        } else {
          router.push("/estimate?journey=codebase");
        }
      } else if (milestone.id === "proof_replay") {
        queueJourneyAction({ type: "proof_replay" });
        setIsOpen(false);
        if (pathname === "/proof") {
          window.dispatchEvent(new CustomEvent("estimator:journey-action", { detail: { type: "proof_replay" } }));
        } else {
          router.push("/proof?journey=replay");
        }
      }
    } catch (err) {
      console.error("Failed to run milestone", err);
      router.push(milestone.targetRoute);
    } finally {
      setIsExecuting(false);
    }
  };

  const completedCount = Object.keys(state.completed).filter((k) => state.completed[k]).length;
  const isSelectedDone = Boolean(state.completed[selectedMilestone.id]);

  return (
    <div className="fixed bottom-4 right-4 z-50 no-print font-sans select-none">
      {!isOpen ? (
        <button
          type="button"
          onClick={() => setIsOpen(true)}
          className="group flex items-center gap-2.5 rounded-full border border-[var(--hairline-strong)] bg-[var(--surface-1)]/95 px-3 py-1.5 text-xs text-[var(--ink)] shadow-[0_12px_32px_rgba(0,0,0,0.85)] backdrop-blur-md transition-all hover:border-[var(--primary)] hover:bg-[var(--surface-2)]"
          title="Interactive Evaluation Journey (Ctrl/⌘ + J)"
        >
          <span className="flex h-5 w-5 items-center justify-center rounded-full bg-[var(--surface-3)] text-[10px] font-mono font-medium text-[var(--primary)] border border-[var(--hairline)]">
            {completedCount}/{JOURNEY_MILESTONES.length}
          </span>
          <span className="font-medium text-[var(--ink-muted)] group-hover:text-[var(--ink)]">
            Journey: {selectedMilestone.title}
          </span>
          <kbd className="hidden sm:inline-block rounded border border-[var(--hairline)] bg-[var(--surface-2)] px-1.5 py-0.5 text-[10px] font-mono text-[var(--ink-tertiary)]">
            ⌘J
          </kbd>
        </button>
      ) : (
        <div className="w-[390px] max-w-[calc(100vw-2rem)] rounded-xl border border-[var(--hairline-strong)] bg-[var(--surface-1)] p-4 shadow-[0_24px_64px_rgba(0,0,0,0.95)] backdrop-blur-xl animate-in fade-in zoom-in-95 duration-150">
          {/* Header */}
          <div className="flex items-center justify-between border-b border-[var(--hairline)] pb-3">
            <div className="flex items-center gap-2">
              <span className="h-2 w-2 rounded-full bg-[var(--primary)] animate-pulse" />
              <span className="text-xs font-semibold uppercase tracking-wider text-[var(--ink)]">
                Evaluation Journey
              </span>
            </div>
            <div className="flex items-center gap-2">
              <span className="num text-xs font-mono text-[var(--ink-muted)]">
                {completedCount}/{JOURNEY_MILESTONES.length}
              </span>
              <button
                type="button"
                onClick={() => setIsOpen(false)}
                className="h-6 w-6 rounded-md border border-transparent text-center text-xs text-[var(--ink-tertiary)] hover:border-[var(--hairline)] hover:text-[var(--ink)]"
                aria-label="Close"
              >
                ✕
              </button>
            </div>
          </div>

          {/* Progress Bar */}
          <div className="my-2.5 h-1 w-full overflow-hidden rounded-full bg-[var(--surface-3)]">
            <div
              className="h-full bg-[var(--primary)] transition-all duration-300"
              style={{ width: `${(completedCount / JOURNEY_MILESTONES.length) * 100}%` }}
            />
          </div>

          {/* Step Pill Selectors */}
          <div className="grid grid-cols-4 gap-1.5 py-1">
            {JOURNEY_MILESTONES.map((m, idx) => {
              const isDone = Boolean(state.completed[m.id]);
              const isSelected = selectedMilestone.id === m.id;
              return (
                <button
                  key={m.id}
                  type="button"
                  onClick={() => setSelectedMilestone(m)}
                  className={`flex flex-col items-center justify-center rounded-lg border py-1.5 transition ${
                    isSelected
                      ? "border-[var(--primary)] bg-[var(--surface-2)] text-[var(--ink)]"
                      : isDone
                        ? "border-[rgba(39,166,68,0.3)] bg-[var(--surface-2)]/60 text-[var(--success)]"
                        : "border-[var(--hairline)] bg-[var(--surface-2)]/30 text-[var(--ink-tertiary)] hover:border-[var(--hairline-strong)] hover:text-[var(--ink-muted)]"
                  }`}
                >
                  <span className="num text-[10px] font-mono font-medium">{m.number}</span>
                  <span className="text-[10px]">{isDone ? "✓" : `Step ${idx + 1}`}</span>
                </button>
              );
            })}
          </div>

          {/* Selected Step Card */}
          <div className="mt-2.5 rounded-lg border border-[var(--hairline)] bg-[var(--surface-2)] p-3">
            <div className="flex items-center justify-between">
              <span className="num text-[11px] font-mono text-[var(--primary)] font-semibold">
                {selectedMilestone.number} · {selectedMilestone.keyMetric}
              </span>
              {isSelectedDone && (
                <span className="text-[10px] font-medium text-[var(--success)]">
                  ✓ Step Tested
                </span>
              )}
            </div>

            <h4 className="mt-1 text-xs font-semibold text-[var(--ink)]">
              {selectedMilestone.title}
            </h4>
            <p className="mt-1 text-[11px] leading-relaxed text-[var(--ink-subtle)]">
              {selectedMilestone.description}
            </p>

            <div className="mt-2 rounded border border-[var(--hairline)] bg-[var(--canvas)] p-2">
              <div className="text-[9px] font-semibold uppercase tracking-wider text-[var(--primary)]">
                Aha! Moment
              </div>
              <div className="text-[10px] leading-relaxed text-[var(--ink-muted)]">
                {selectedMilestone.ahaMoment}
              </div>
            </div>

            <div className="mt-3 flex items-center justify-between gap-2 pt-2 border-t border-[var(--hairline)]">
              <button
                type="button"
                onClick={resetJourney}
                className="text-[10px] text-[var(--ink-tertiary)] hover:text-[var(--ink-muted)] underline"
              >
                Reset Track
              </button>
              <button
                type="button"
                disabled={isExecuting}
                onClick={() => runMilestone(selectedMilestone)}
                className="btn btn-primary py-1 px-3 text-xs"
              >
                {isExecuting ? <Spinner className="h-3 w-3" /> : null}
                <span>{isExecuting ? "Executing…" : `⚡ ${selectedMilestone.actionLabel}`}</span>
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
