"use client";

import { useState } from "react";
import type { VoIQuestion } from "@/lib/types";
import { featureLabel } from "@/lib/features";
import { fmtInt } from "@/lib/format";
import { EmptyState } from "./ui";
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

/** Ranked clarifying questions by Value of Information (spec §4.3). */
export function RankedQuestionsList({ questions }: { questions: VoIQuestion[] }) {
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
        <div className="flex items-center gap-2">
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
            {questions.length} open question{questions.length === 1 ? "" : "s"}
          </span>
        </div>
        <button type="button" className="btn btn-lime" onClick={copyAll}>
          {copied ? "✓ Copied" : "Copy all"}
        </button>
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

      <ol className="space-y-2">
        {questions.map((question, index) => (
          <li key={question.feature} className="panel-2 p-3">
            <div className="flex items-start justify-between gap-3">
              <div className="flex min-w-0 items-start gap-2.5">
                <span className="num mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded border border-[var(--border-strong)] text-[10px] text-[var(--cyan)]">
                  {index + 1}
                </span>
                <div>
                  <div className="text-sm leading-5 text-[var(--text)]">
                    {language === "vi"
                      ? question.question_vi
                      : question.question_en}
                  </div>
                  <div className="mt-1 text-[11px] text-[var(--faint)]">
                    {featureLabel(question.feature)} ·{" "}
                    <Term term="Value of Information" tip={GLOSSARY.voi}>
                      impact
                    </Term>
                  </div>
                </div>
              </div>
              <span
                className="chip chip-unknown num shrink-0"
                title={`Estimated P50 swing if answered: about ${fmtInt(question.impact_days)} days`}
              >
                +{fmtInt(question.impact_days)} d
              </span>
            </div>
          </li>
        ))}
      </ol>
    </div>
  );
}
