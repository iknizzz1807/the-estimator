"use client";

import { useState } from "react";
import type { AnswersMap, VoIQuestion } from "@/lib/types";
import { featureLabel } from "@/lib/features";
import { fmtInt } from "@/lib/format";
import { EmptyState, Spinner } from "./ui";
import { GLOSSARY, Term } from "./Tooltip";

export type QuestionLanguage = "en" | "vi";

export function formatQuestions(
  questions: VoIQuestion[],
  language: QuestionLanguage
): string {
  return questions
    .map((question, index) => {
      const text = language === "vi" ? question.question_vi : question.question_en;
      return `${index + 1}. ${text} (impact ≈ ${fmtInt(question.impact_days)} days)`;
    })
    .join("\n\n");
}

async function copyText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
}

/**
 * Ranked clarifying questions by Value of Information (spec §4.3) + the
 * interactive answer flow (contract v0.2): Có/Không re-calls /api/estimate
 * with the accumulated answers, which shrinks the interval. Answer-refinement
 * calls are side-effect free — no new project row is stored.
 */
export function RankedQuestionsList({
  questions,
  answers = {},
  onAnswer,
  onClearAnswers,
  busy = false,
}: {
  questions: VoIQuestion[];
  /** Accumulated yes(1)/no(0) answers keyed by feature. */
  answers?: AnswersMap;
  onAnswer?: (feature: string, value: 0 | 1) => void;
  onClearAnswers?: () => void;
  /** True while a refinement estimate is in flight. */
  busy?: boolean;
}) {
  const [language, setLanguage] = useState<QuestionLanguage>("en");
  const [copied, setCopied] = useState(false);
  const [copyFailed, setCopyFailed] = useState(false);

  if (questions.length === 0) {
    return (
      <EmptyState
        title="No open questions"
        hint="Every feature was resolved from the email. Nothing left to ask — good sign."
      />
    );
  }

  const answeredCount = questions.filter(
    (question) => answers[question.feature] !== undefined
  ).length;
  const openCount = questions.length - answeredCount;

  const copyAll = async () => {
    const ok = await copyText(formatQuestions(questions, language));
    setCopied(ok);
    setCopyFailed(!ok);
    window.setTimeout(() => {
      setCopied(false);
      setCopyFailed(false);
    }, 2500);
  };

  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <span className="inline-flex overflow-hidden rounded-md border border-[var(--border)]">
            {(["en", "vi"] as const).map((lang) => (
              <button
                key={lang}
                type="button"
                className={`px-2.5 py-1 text-[11px] uppercase tracking-wider transition ${
                  language === lang
                    ? "bg-[rgba(34,211,238,0.15)] text-[var(--cyan)]"
                    : "text-[var(--dim)] hover:text-[var(--text)]"
                }`}
                aria-pressed={language === lang}
                onClick={() => setLanguage(lang)}
              >
                {lang === "en" ? "English" : "Tiếng Việt"}
              </button>
            ))}
          </span>
          <span className="chip chip-unknown">
            {openCount} open question{openCount === 1 ? "" : "s"}
          </span>
          {answeredCount > 0 && (
            <span className="chip chip-ok">
              ✓ {answeredCount} answered
            </span>
          )}
          {busy && (
            <span className="chip chip-info">
              <Spinner className="h-2.5 w-2.5" /> refining range…
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          {answeredCount > 0 && onClearAnswers && (
            <button
              type="button"
              className="text-[11px] text-[var(--dim)] underline decoration-dotted underline-offset-2 hover:text-[var(--text)]"
              onClick={onClearAnswers}
              title="Discard all answers and go back to the original range"
            >
              Clear answers
            </button>
          )}
          <button type="button" className="btn btn-lime" onClick={copyAll}>
            {copied ? "✓ Copied" : "Copy all"}
          </button>
        </div>
      </div>

      {copyFailed && (
        <div className="banner banner-amber mb-2" role="alert">
          <span aria-hidden>⚠</span>
          <span className="text-xs">
            Clipboard is blocked in this browser context — select the text
            manually.
          </span>
        </div>
      )}

      <p className="mb-3 text-[11px] leading-4 text-[var(--faint)]">
        Click <span className="font-medium text-[var(--dim)]">Có</span> (yes, in
        scope) or <span className="font-medium text-[var(--dim)]">Không</span>{" "}
        (no) — the estimate re-runs with your answers and the range narrows.
        Refinements are not stored as projects.
      </p>

      <ol className="space-y-2">
        {questions.map((question, index) => {
          const chosen = answers[question.feature];
          const answered = chosen !== undefined;
          return (
            <li
              key={question.feature}
              className={`panel-2 p-3 transition ${answered ? "opacity-75" : ""}`}
            >
              <div className="flex items-start justify-between gap-3">
                <div className="flex min-w-0 items-start gap-2.5">
                  <span
                    className={`num mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded border text-[10px] ${
                      answered
                        ? "border-[rgba(163,230,53,0.6)] text-[var(--lime)]"
                        : "border-[var(--border-strong)] text-[var(--cyan)]"
                    }`}
                    title={answered ? "Answered" : `Rank ${index + 1} by impact`}
                  >
                    {answered ? "✓" : index + 1}
                  </span>
                  <div>
                    <div
                      className={`text-sm leading-5 ${
                        answered
                          ? "text-[var(--dim)]"
                          : "text-[var(--text)]"
                      }`}
                    >
                      {language === "vi"
                        ? question.question_vi
                        : question.question_en}
                    </div>
                    <div className="mt-1 text-[11px] text-[var(--faint)]">
                      {featureLabel(question.feature)} ·{" "}
                      <Term term="Value of Information" tip={GLOSSARY.voi}>
                        impact
                      </Term>
                      {answered && (
                        <span className="ml-2 text-[var(--lime)]">
                          answered: {chosen === 1 ? "Có (in scope)" : "Không (out of scope)"}
                        </span>
                      )}
                    </div>
                  </div>
                </div>

                <div className="flex shrink-0 flex-col items-end gap-1.5">
                  <div
                    className="flex items-center gap-1"
                    role="group"
                    aria-label={`Answer question about ${featureLabel(question.feature)}`}
                  >
                    <button
                      type="button"
                      disabled={busy}
                      aria-pressed={chosen === 1}
                      className={`btn px-2.5 py-0.5 text-xs ${
                        chosen === 1 ? "btn-lime" : ""
                      }`}
                      title="Có — yes, this capability is in scope. Re-runs the estimate with the accumulated answers (nothing is stored)."
                      onClick={() => onAnswer?.(question.feature, 1)}
                    >
                      Có
                    </button>
                    <button
                      type="button"
                      disabled={busy}
                      aria-pressed={chosen === 0}
                      className={`btn px-2.5 py-0.5 text-xs ${
                        chosen === 0 ? "btn-warn" : ""
                      }`}
                      title="Không — no, this capability is not needed. Re-runs the estimate with the accumulated answers (nothing is stored)."
                      onClick={() => onAnswer?.(question.feature, 0)}
                    >
                      Không
                    </button>
                  </div>
                  <span
                    className="chip chip-unknown num shrink-0"
                    title={`Estimated P50 swing if answered: about ${fmtInt(question.impact_days)} days`}
                  >
                    +{fmtInt(question.impact_days)} d
                  </span>
                </div>
              </div>
            </li>
          );
        })}
      </ol>
    </div>
  );
}
