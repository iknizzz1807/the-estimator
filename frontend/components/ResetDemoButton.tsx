"use client";

import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { api } from "@/lib/api";
import { errMessage } from "@/lib/hooks";
import { Spinner } from "./ui";

type Toast = { tone: "ok" | "error"; title: string; detail?: string };

/**
 * "Reset demo data" (contract v0.2, POST /api/reset): confirm → reseed the
 * demo DB to the pristine synthetic history → success toast + a gentle
 * refresh signal so every mounted data hook refetches (no hard reload).
 * Styled with Linear subtle elevated surfaces, hairline borders, and semantic accents.
 */
export default function ResetDemoButton() {
  const [loading, setLoading] = useState(false);
  const [toast, setToast] = useState<Toast | null>(null);
  const [mounted, setMounted] = useState(false);

  useEffect(() => setMounted(true), []);

  useEffect(() => {
    if (!toast) return;
    const timer = window.setTimeout(() => setToast(null), 5500);
    return () => window.clearTimeout(timer);
  }, [toast]);

  const reset = async () => {
    const confirmed = window.confirm(
      "Reset demo data to the pristine synthetic history?\n\n" +
        "Projects created by estimates (P241+) and recorded actuals will be lost. " +
        "The model is retrained and the replay cache refreshed."
    );
    if (!confirmed) return;
    setLoading(true);
    try {
      const result = await api.resetDemo();
      setToast({
        tone: "ok",
        title: "Demo data reset",
        detail: `${result.projects_count} pristine projects reseeded · model retrained`,
      });
      // Gentle refresh: refetch mounted resources instead of a page reload.
      window.setTimeout(
        () => window.dispatchEvent(new Event("estimator:retry")),
        900
      );
    } catch (err) {
      setToast({
        tone: "error",
        title: "Reset failed — nothing changed",
        detail: errMessage(err),
      });
    } finally {
      setLoading(false);
    }
  };

  return (
    <>
      <button
        type="button"
        className="btn btn-warn w-full justify-center py-1.5 text-xs font-medium"
        disabled={loading}
        onClick={() => void reset()}
        title="Reseed the demo database (POST /api/reset) — wipes estimate-created projects and recorded actuals."
      >
        {loading ? <Spinner className="h-3 w-3" /> : null}
        {loading ? "Resetting…" : "Reset demo data"}
      </button>

      {mounted && toast
        ? createPortal(
            <div
              role="status"
              aria-live="polite"
              className={`fixed bottom-4 right-4 z-[100] max-w-sm rounded-lg border border-[var(--hairline-strong)] bg-[var(--surface-2)] p-4 pr-8 text-sm shadow-[0_16px_36px_rgba(0,0,0,0.85)] ${
                toast.tone === "ok"
                  ? "border-l-2 border-l-[var(--success)]"
                  : "border-l-2 border-l-[var(--danger)]"
              }`}
            >
              <div className="flex items-center gap-2">
                <span
                  className={`h-2 w-2 rounded-full ${
                    toast.tone === "ok" ? "bg-[var(--success)]" : "bg-[var(--danger)]"
                  }`}
                  aria-hidden
                />
                <div className="font-medium text-xs text-[var(--ink)]">{toast.title}</div>
              </div>
              {toast.detail && (
                <div className="mt-1 text-xs text-[var(--ink-subtle)] pl-4">{toast.detail}</div>
              )}
              <button
                type="button"
                className="absolute right-2.5 top-2.5 text-xs text-[var(--ink-tertiary)] hover:text-[var(--ink)]"
                onClick={() => setToast(null)}
                aria-label="Dismiss notification"
              >
                ✕
              </button>
            </div>,
            document.body
          )
        : null}
    </>
  );
}
