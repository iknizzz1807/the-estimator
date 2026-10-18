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
 * Ranked clarifying questions by Value of Information (spec §4.3) + interactive
 * answer flow (contract v0.2). Styled like Linear issue/task rows with compact
 * Yes/No pill buttons, VOI impact tag in tabular mono, and crisp hairline details.
 */
export function RankedQuestionsList({
  questions,
  otherUnknown = [],
  answers = {},
  onAnswer,
  onClearAnswers,
  busy = false,
}: {
  questions: VoIQuestion[];
  /**
   * Unknown features NOT in the ranked list (lower impact by construction). The
   * PM can still pin them, but the copy is explicit that guessing is worse than
   * leaving them unknown (DECISIONS D29).
   */
  otherUnknown?: string[];
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
  const [showAllUnknown, setShowAllUnknown] = useState(false);

  if (questions.length === 0 && otherUnknown.length === 0) {
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
    <div className="space-y-3">
      {/* Action Header */}
      <div className="flex flex-wrap items-center justify-between gap-2.5 pb-1">
        <div className="flex flex-wrap items-center gap-2">
          {/* Linear Segmented Toggle */}
          <div className="inline-flex rounded-md border border-[#23252a] bg-[#0f1011] p-0.5">
            {(["en", "vi"] as const).map((lang) => (
              <button
                key={lang}
                type="button"
                className={`rounded px-2.5 py-1 text-[11px] font-medium tracking-wide transition-colors ${
                  language === lang
                    ? "bg-[#18191a] text-[#f7f8f8] shadow-sm"
                    : "text-[#8a8f98] hover:text-[#f7f8f8]"
                }`}
                aria-pressed={language === lang}
                onClick={() => setLanguage(lang)}
              >
                {lang === "en" ? "EN" : "VI"}
              </button>
            ))}
          </div>

          <span className="inline-flex items-center gap-1.5 rounded-full border border-[rgba(245,158,11,0.3)] bg-[rgba(245,158,11,0.1)] px-2.5 py-0.5 font-mono text-[11px] tabular-nums text-[#f59e0b]">
            <span className="h-1.5 w-1.5 rounded-full bg-[#f59e0b]" />
            {openCount} open
          </span>

          {answeredCount > 0 && (
            <span className="inline-flex items-center gap-1.5 rounded-full border border-[rgba(39,166,68,0.3)] bg-[rgba(39,166,68,0.1)] px-2.5 py-0.5 font-mono text-[11px] tabular-nums text-[#27a644]">
              <span className="h-1.5 w-1.5 rounded-full bg-[#27a644]" />
              {answeredCount} answered
            </span>
          )}

          {busy && (
            <span className="inline-flex items-center gap-1.5 rounded-full border border-[rgba(94,106,210,0.3)] bg-[rgba(94,106,210,0.1)] px-2.5 py-0.5 text-[11px] text-[#828fff]">
              <Spinner className="h-2.5 w-2.5" />
              <span>refining…</span>
            </span>
          )}
        </div>

        <div className="flex items-center gap-2">
          {answeredCount > 0 && onClearAnswers && (
            <button
              type="button"
              className="text-[11px] text-[#8a8f98] underline decoration-dotted underline-offset-2 transition-colors hover:text-[#f7f8f8]"
              onClick={onClearAnswers}
              title="Discard all answers and go back to original range"
            >
              Clear answers
            </button>
          )}
          <button
            type="button"
            className="inline-flex items-center gap-1 rounded-md border border-[#23252a] bg-[#141516] px-2.5 py-1 text-xs font-medium text-[#f7f8f8] transition-colors hover:border-[#34343a] hover:bg-[#18191a]"
            onClick={copyAll}
          >
            {copied ? "✓ Copied" : "Copy all"}
          </button>
        </div>
      </div>

      {copyFailed && (
        <div
          className="flex items-center gap-2 rounded-lg border border-[rgba(245,158,11,0.3)] bg-[rgba(245,158,11,0.08)] px-3 py-2 text-xs text-[#f59e0b]"
          role="alert"
        >
          <span aria-hidden="true">⚠</span>
          <span>
            Clipboard blocked — please select text manually.
          </span>
        </div>
      )}

      {/* Linear Task/Issue Rows List */}
      <ol className="space-y-2">
        {questions.map((question, index) => {
          const chosen = answers[question.feature];
          const answered = chosen !== undefined;
          return (
            <li
              key={question.feature}
              className={`group flex items-start justify-between gap-3 rounded-lg border bg-[#0f1011] p-3 transition-colors ${
                answered
                  ? "border-[#23252a]/80 bg-[#0f1011]/80 opacity-80"
                  : "border-[#23252a] hover:border-[#34343a] hover:bg-[#141516]"
              }`}
            >
              <div className="flex min-w-0 items-start gap-3">
                {/* Issue/Task Index Indicator */}
                <span
                  className={`mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded border font-mono text-[10px] tabular-nums transition-colors ${
                    answered
                      ? "border-[rgba(39,166,68,0.4)] bg-[rgba(39,166,68,0.1)] text-[#27a644]"
                      : "border-[#23252a] bg-[#141516] text-[#8a8f98] group-hover:border-[#34343a] group-hover:text-[#f7f8f8]"
                  }`}
                  title={answered ? "Answered" : `Rank ${index + 1} by impact`}
                >
                  {answered ? "✓" : index + 1}
                </span>

                <div className="min-w-0">
                  <div
                    className={`text-[13px] leading-snug transition-colors ${
                      answered ? "text-[#8a8f98]" : "text-[#f7f8f8]"
                    }`}
                  >
                    {language === "vi"
                      ? question.question_vi
                      : question.question_en}
                  </div>

                  <div className="mt-1 flex flex-wrap items-center gap-2 text-[11px] text-[#62666d]">
                    <span className="font-medium text-[#8a8f98]">
                      {featureLabel(question.feature)}
                    </span>
                    <span>·</span>
                    <Term term="Value of Information" tip={GLOSSARY.voi}>
                      <span className="text-[#62666d] underline decoration-dotted underline-offset-2">
                        impact
                      </span>
                    </Term>
                    {answered && (
                      <span className="text-[#27a644]">
                        · Answered: {chosen === 1 ? "Có (In scope)" : "Không (Out of scope)"}
                      </span>
                    )}
                  </div>
                </div>
              </div>

              {/* Action Controls & Tabular Mono VOI Tag */}
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
                    className={`rounded-full px-2.5 py-0.5 font-mono text-xs font-medium transition-colors ${
                      chosen === 1
                        ? "border border-[rgba(94,106,210,0.6)] bg-[rgba(94,106,210,0.18)] text-[#828fff]"
                        : "border border-[#23252a] bg-[#141516] text-[#8a8f98] hover:border-[#34343a] hover:text-[#f7f8f8]"
                    } disabled:cursor-not-allowed disabled:opacity-50`}
                    title="Có — yes, this capability is in scope."
                    onClick={() => onAnswer?.(question.feature, 1)}
                  >
                    Có
                  </button>

                  <button
                    type="button"
                    disabled={busy}
                    aria-pressed={chosen === 0}
                    className={`rounded-full px-2.5 py-0.5 font-mono text-xs font-medium transition-colors ${
                      chosen === 0
                        ? "border border-[rgba(245,158,11,0.5)] bg-[rgba(245,158,11,0.15)] text-[#f59e0b]"
                        : "border border-[#23252a] bg-[#141516] text-[#8a8f98] hover:border-[#34343a] hover:text-[#f7f8f8]"
                    } disabled:cursor-not-allowed disabled:opacity-50`}
                    title="Không — no, this capability is not needed."
                    onClick={() => onAnswer?.(question.feature, 0)}
                  >
                    Không
                  </button>
                </div>

                <span
                  className="inline-flex items-center rounded-full border border-[#23252a] bg-[#141516] px-2 py-0.5 font-mono text-[10.5px] tabular-nums text-[#8a8f98]"
                  title={`Estimated P50 swing if answered: about ${fmtInt(question.impact_days)} days`}
                >
                  +{fmtInt(question.impact_days)} days
                </span>
              </div>
            </li>
          );
        })}
      </ol>

      {/* Lower-impact unknowns: opt-in, with honest copy. Answering them is a
          legitimate way to reach a fully-known vector (method flips to "point"),
          but guessing produces false certainty — so the default is collapsed. */}
      {otherUnknown.length > 0 && (
        <div className="space-y-2 border-t border-[#23252a] pt-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <button
              type="button"
              className="inline-flex items-center gap-1.5 rounded-md border border-[#23252a] bg-[#141516] px-2.5 py-1 text-xs font-medium text-[#f7f8f8] transition-colors hover:border-[#34343a] hover:bg-[#18191a]"
              aria-expanded={showAllUnknown}
              onClick={() => setShowAllUnknown((value) => !value)}
            >
              {showAllUnknown ? "▾" : "▸"} {showAllUnknown ? "Hide" : "Show all"}{" "}
              {otherUnknown.length} lower-impact unknown
              {otherUnknown.length === 1 ? "" : "s"}
            </button>
            <span className="text-[11px] text-[#62666d]">
              Answer only what you actually know — leaving a feature unknown keeps
              the range honest.
            </span>
          </div>

          {showAllUnknown && (
            <ul className="space-y-1.5">
              {otherUnknown.map((feature) => {
                const chosen = answers[feature];
                return (
                  <li
                    key={feature}
                    className="flex items-center justify-between gap-3 rounded-lg border border-[#23252a] bg-[#0f1011] px-3 py-2"
                  >
                    <div className="min-w-0">
                      <span className="text-[12.5px] text-[#f7f8f8]">
                        {featureLabel(feature)}
                      </span>
                      {chosen !== undefined && (
                        <span className="ml-2 text-[11px] text-[#27a644]">
                          · {chosen === 1 ? "Có (In scope)" : "Không (Out of scope)"}
                        </span>
                      )}
                    </div>
                    <div
                      className="flex shrink-0 items-center gap-1"
                      role="group"
                      aria-label={`Answer question about ${featureLabel(feature)}`}
                    >
                      <button
                        type="button"
                        disabled={busy}
                        aria-pressed={chosen === 1}
                        className={`rounded-full px-2.5 py-0.5 font-mono text-xs font-medium transition-colors ${
                          chosen === 1
                            ? "border border-[rgba(94,106,210,0.6)] bg-[rgba(94,106,210,0.18)] text-[#828fff]"
                            : "border border-[#23252a] bg-[#141516] text-[#8a8f98] hover:border-[#34343a] hover:text-[#f7f8f8]"
                        } disabled:cursor-not-allowed disabled:opacity-50`}
                        title="Có — yes, this capability is in scope."
                        onClick={() => onAnswer?.(feature, 1)}
                      >
                        Có
                      </button>
                      <button
                        type="button"
                        disabled={busy}
                        aria-pressed={chosen === 0}
                        className={`rounded-full px-2.5 py-0.5 font-mono text-xs font-medium transition-colors ${
                          chosen === 0
                            ? "border border-[rgba(245,158,11,0.5)] bg-[rgba(245,158,11,0.15)] text-[#f59e0b]"
                            : "border border-[#23252a] bg-[#141516] text-[#8a8f98] hover:border-[#34343a] hover:text-[#f7f8f8]"
                        } disabled:cursor-not-allowed disabled:opacity-50`}
                        title="Không — no, this capability is not needed."
                        onClick={() => onAnswer?.(feature, 0)}
                      >
                        Không
                      </button>
                    </div>
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
