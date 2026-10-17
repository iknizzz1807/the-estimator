"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { api, estimateStream } from "@/lib/api";
import { errMessage, useAsyncData } from "@/lib/hooks";
import { readPrefillEmail, readStoredEstimate } from "@/lib/session";
import {
  STREAM_STEPS,
  type AnswersMap,
  type EstimateResponse,
  type RepoChoice,
  type StreamEvent,
} from "@/lib/types";
import { fmtInt, humanDuration } from "@/lib/format";
import { EmailInput } from "@/components/EmailInput";
import { ScenarioPicker } from "@/components/ImportCSVModal";
import { EstimateChart, MethodBadge, ModeBadge } from "@/components/EstimateChart";
import { FeatureGrid } from "@/components/FeatureCard";
import { SimilarProjectsList } from "@/components/SimilarProjectsList";
import {
  RankedQuestionsList,
  formatQuestions,
} from "@/components/RankedQuestionsList";
import { RangeCompare } from "@/components/RangeCompare";
import { ContributionBar } from "@/components/ContributionBar";
import { PackageBuilder } from "@/components/PackageBuilder";
import { CoefficientsTable } from "@/components/CoefficientsTable";
import { ProposalPrintView } from "@/components/ProposalPrintView";
import { CodebasePanel } from "@/components/CodebasePanel";
import { EmptyState, Panel, Spinner } from "@/components/ui";
import { GLOSSARY, Term } from "@/components/Tooltip";

const STEP_META: Record<string, { title: string; detail: string }> = {
  extracting: { title: "Extracting", detail: "reading the email → 15 features + evidence quotes" },
  validating: { title: "Validating", detail: "evidence quotes checked, low-confidence findings flagged" },
  similar: { title: "Similar projects", detail: "matching against historical projects" },
  estimating: { title: "Estimating", detail: "Ridge + conformal → P10/P50/P90" },
  questions: { title: "Questions", detail: "ranking missing info by Value of Information" },
  done: { title: "Done", detail: "assembling the result" },
};

/** Codebase Lab repo selector (contract v0.2 `repo` body field). */
const REPO_OPTIONS: Array<{
  value: RepoChoice | null;
  label: string;
  hint: string;
}> = [
  { value: null, label: "None", hint: "no codebase context" },
  { value: "demo_a", label: "Demo A (plugin)", hint: "clean plugin-pattern repo" },
  { value: "demo_b", label: "Demo B (spaghetti)", hint: "messy repo — higher friction" },
  { value: "self", label: "This project", hint: "the server's own checkout" },
];

function ProviderBadge({ provider }: { provider: string | undefined }) {
  if (!provider) return null;
  const key = provider.toLowerCase();
  const cls =
    key === "stub"
      ? "chip-unknown"
      : key === "gemini" || key === "openai"
        ? "chip-ok"
        : "";
  const label =
    key === "stub" ? "extractor: stub (offline)" : `extractor: ${key}`;
  return (
    <span className={`chip ${cls}`} title={GLOSSARY.provider}>
      {label}
    </span>
  );
}

export default function EstimatePage() {
  const [email, setEmail] = useState("");
  const [estimate, setEstimate] = useState<EstimateResponse | null>(null);
  const [scenarioTitle, setScenarioTitle] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  const [completedSteps, setCompletedSteps] = useState<string[]>([]);
  const [activeStep, setActiveStep] = useState<string | null>(null);
  const [streamError, setStreamError] = useState<string | null>(null);
  const [validationError, setValidationError] = useState<string | null>(null);
  const [coldNote, setColdNote] = useState(false);
  const [copied, setCopied] = useState(false);
  const [copyNote, setCopyNote] = useState<string | null>(null);
  const [durationMs, setDurationMs] = useState<number | null>(null);
  const [generatedAt, setGeneratedAt] = useState("");
  // Codebase Lab (contract v0.2): repository context for the next run.
  const [repo, setRepo] = useState<RepoChoice | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  // Interactive answers (contract v0.2): derived estimate + original result.
  const [baseEstimate, setBaseEstimate] = useState<EstimateResponse | null>(null);
  const [estimateEmail, setEstimateEmail] = useState("");
  const [answers, setAnswers] = useState<AnswersMap>({});
  const [answering, setAnswering] = useState(false);
  const [answerError, setAnswerError] = useState<string | null>(null);
  const answersRef = useRef<AnswersMap>({});
  const confirmedAnswersRef = useRef<AnswersMap>({});
  const answerSeqRef = useRef(0);

  const health = useAsyncData(() => api.health());
  const scenarios = useAsyncData(() => api.scenarios());

  // Landing-page handoff (scenario loaded → populated view) + cold-start link.
  useEffect(() => {
    const stored = readStoredEstimate();
    if (stored) {
      setEstimate(stored.estimate);
      setBaseEstimate(stored.estimate);
      setScenarioTitle(stored.scenarioTitle ?? null);
      setCompletedSteps([...STREAM_STEPS]);
    }
    const prefill = readPrefillEmail();
    if (prefill) {
      setEmail(prefill);
      setEstimateEmail(prefill);
    }
    setColdNote(new URLSearchParams(window.location.search).get("cold") === "1");
    setGeneratedAt(new Date().toLocaleString());
  }, []);

  const resetAnswerState = () => {
    answerSeqRef.current += 1;
    answersRef.current = {};
    confirmedAnswersRef.current = {};
    setAnswers({});
    setAnswering(false);
    setAnswerError(null);
  };

  const runEstimate = async () => {
    const text = email.trim();
    if (!text) {
      setValidationError("Please paste the client email before estimating.");
      return;
    }
    setValidationError(null);
    setStreamError(null);
    setEstimate(null);
    setBaseEstimate(null);
    setScenarioTitle(null);
    setDurationMs(null);
    resetAnswerState();
    setRunning(true);
    setCompletedSteps([]);
    setActiveStep(STREAM_STEPS[0]);
    const controller = new AbortController();
    abortRef.current = controller;
    const startedAt = performance.now();

    try {
      await estimateStream(text, (event: StreamEvent) => {
        if (event.type === "step" && event.step) {
          const index = (STREAM_STEPS as readonly string[]).indexOf(event.step);
          if (index >= 0) {
            setCompletedSteps([...STREAM_STEPS.slice(0, index)]);
            setActiveStep(event.step);
          }
        } else if (event.type === "result" && event.result) {
          setEstimate(event.result);
          setBaseEstimate(event.result);
          setEstimateEmail(text);
          setCompletedSteps([...STREAM_STEPS]);
          setActiveStep(null);
          setDurationMs(performance.now() - startedAt);
        } else if (event.type === "error") {
          setStreamError(event.message ?? "Estimation failed — please retry.");
          setActiveStep(null);
        }
      }, controller.signal, repo);
    } catch (err) {
      if (!controller.signal.aborted) {
        setStreamError(errMessage(err));
      } else {
        setStreamError("Run cancelled — the estimate was not stored.");
      }
      setActiveStep(null);
    } finally {
      setRunning(false);
    }
  };

  /**
   * Answer-refinement (contract v0.2): re-call POST /api/estimate with the
   * accumulated `answers` map. Side-effect free on the backend — no new
   * project row — so the interval can be refined as often as needed.
   */
  const applyAnswers = async (feature: string, value: 0 | 1) => {
    if (!estimateEmail.trim() || answering) return;
    const current = answersRef.current;
    if (current[feature] === value) return;
    const next: AnswersMap = { ...current, [feature]: value };
    answersRef.current = next;
    setAnswers(next);
    setAnswerError(null);
    setAnswering(true);
    const seq = ++answerSeqRef.current;
    try {
      const refined = await api.estimate(estimateEmail, next, repo);
      if (seq !== answerSeqRef.current) return;
      setEstimate(refined);
      confirmedAnswersRef.current = next;
    } catch (err) {
      if (seq !== answerSeqRef.current) return;
      answersRef.current = confirmedAnswersRef.current;
      setAnswers(confirmedAnswersRef.current);
      setAnswerError(errMessage(err));
    } finally {
      if (seq === answerSeqRef.current) setAnswering(false);
    }
  };

  const clearAnswers = () => {
    resetAnswerState();
    if (baseEstimate) setEstimate(baseEstimate);
  };

  const cancelRun = () => {
    abortRef.current?.abort();
    setRunning(false);
    setActiveStep(null);
    setCompletedSteps([]);
    setStreamError("Run cancelled — the estimate was not stored.");
  };

  const extraNotes = useMemo(() => {
    if (!estimate) return [];
    const map = new Map(estimate.findings.map((f) => [f.name, f.value]));
    const alreadyWarned = (pattern: RegExp) =>
      estimate.warnings.some((warning) => pattern.test(warning));
    const notes: string[] = [];
    if (
      map.get("realtime_ui") === 1 &&
      map.get("offline_mode") === 1 &&
      // The backend already flags this conflict (Vietnamese detail).
      !alreadyWarned(/realtime_ui|offline_mode|mâu thuẫn/i)
    ) {
      notes.push(
        "Conflicting requirements flagged for review: real-time UI and offline mode are both present."
      );
    }
    if (
      estimate.findings.length > 0 &&
      estimate.findings.every((f) => f.value === null) &&
      // Backend emits its own (Vietnamese) "no features" warning.
      !alreadyWarned(/no features|không tìm thấy features/i)
    ) {
      notes.push("No features were detected — please review the email before trusting the range.");
    }
    return notes;
  }, [estimate]);

  const copyQuestions = async () => {
    if (!estimate) return;
    try {
      await navigator.clipboard.writeText(formatQuestions(estimate.questions, "en"));
      setCopied(true);
      setCopyNote(null);
      window.setTimeout(() => setCopied(false), 2500);
    } catch {
      // Clipboard needs a secure context (https/localhost) — never dress this
      // up as a failed estimate.
      setCopyNote(
        "Clipboard is blocked here (needs https or localhost) — use “Copy all” in the questions panel, or select the text manually."
      );
      window.setTimeout(() => setCopyNote(null), 6000);
    }
  };

  const topScore = estimate?.similar_projects[0]?.score ?? null;
  const baseQuestions = baseEstimate?.questions ?? estimate?.questions ?? [];
  const answeredCount = Object.keys(answers).length;
  const unknownCount = estimate
    ? estimate.findings.filter((f) => f.value === null).length
    : 0;

  return (
    <div className="space-y-5">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold">New estimate</h1>
          <p className="mt-0.5 text-xs text-[var(--dim)]">
            Paste an email → calibrated range + the questions worth asking.
          </p>
        </div>
        <div className="flex items-center gap-2">
          {scenarioTitle && <span className="chip chip-info">scenario {scenarioTitle}</span>}
          <ProviderBadge provider={health.data?.llm_provider} />
        </div>
      </header>

      {coldNote && (
        <div className="banner banner-cyan no-print" role="note">
          <span aria-hidden>◐</span>
          <div className="text-xs">
            <span className="font-medium">Cold start:</span> with no (or less
            than 10 projects of) history, the range uses documented industry
            multipliers and is deliberately wider. Feature extraction and
            questions work exactly the same.
          </div>
        </div>
      )}

      {copyNote && (
        <div className="banner banner-amber no-print" role="alert">
          <span aria-hidden>⚠</span>
          <span className="text-xs">{copyNote}</span>
        </div>
      )}

      <Panel title="Input">
        <div className="space-y-3">
          <ScenarioPicker
            scenarios={scenarios.data ?? []}
            loading={scenarios.loading}
            disabled={running}
            onPick={(scenario) => {
              setEmail(scenario.email_text);
              setValidationError(null);
              setScenarioTitle(null);
            }}
          />
          <EmailInput
            value={email}
            onChange={(value) => {
              setEmail(value);
              if (validationError) setValidationError(null);
            }}
            onSubmit={runEstimate}
            running={running}
            validationError={validationError}
          />
          <div className="flex flex-wrap items-center gap-2 border-t border-[var(--border)] pt-3">
            <span className="text-[11px] uppercase tracking-[0.1em] text-[var(--dim)]">
              Codebase context
            </span>
            <div
              className="flex flex-wrap gap-1.5"
              role="radiogroup"
              aria-label="Codebase context repository"
            >
              {REPO_OPTIONS.map((option) => {
                const active = repo === option.value;
                return (
                  <button
                    key={option.label}
                    type="button"
                    role="radio"
                    aria-checked={active}
                    title={option.hint}
                    disabled={running}
                    onClick={() => setRepo(option.value)}
                    className={`chip cursor-pointer disabled:cursor-not-allowed disabled:opacity-45 ${
                      active ? "chip-info" : ""
                    }`}
                  >
                    {option.label}
                  </button>
                );
              })}
            </div>
            {repo && (
              <span className="text-[11px] text-[var(--faint)]">
                {REPO_OPTIONS.find((option) => option.value === repo)?.hint}
              </span>
            )}
            {estimate && !running && (estimate.codebase?.repo ?? null) !== repo && (
              <span className="chip chip-unknown">press Estimate to apply</span>
            )}
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              className="btn btn-primary"
              disabled={running}
              onClick={runEstimate}
            >
              {running ? <Spinner className="h-3.5 w-3.5" /> : null}
              {running ? "Estimating…" : "Estimate"}
            </button>
            {running && (
              <button type="button" className="btn" onClick={cancelRun}>
                Cancel
              </button>
            )}
            {estimate && !running && (
              <span className="num text-[11px] text-[var(--faint)]">
                {estimate.project_id ?? "refined"}
                {durationMs !== null ? ` · ${humanDuration(durationMs)}` : ""}
              </span>
            )}
          </div>
        </div>
      </Panel>

      {running && (
        <Panel
          title="Pipeline"
          subtitle="Live progress streamed from POST /api/estimate/stream (SSE)"
        >
          <ol className="space-y-1.5" aria-live="polite">
            {STREAM_STEPS.map((step) => {
              const done = completedSteps.includes(step);
              const active = activeStep === step && !done;
              return (
                <li key={step} className="flex items-center gap-3">
                  <span
                    className={`flex h-5 w-5 items-center justify-center rounded-full border text-[10px] ${
                      done
                        ? "border-[var(--success)] text-[var(--success)] bg-[rgba(39,166,68,0.1)]"
                        : active
                          ? "border-[var(--primary)] text-[var(--primary)] bg-[rgba(94,106,210,0.1)]"
                          : "border-[var(--hairline)] text-[var(--ink-tertiary)]"
                    }`}
                  >
                    {done ? "✓" : active ? <Spinner className="h-2.5 w-2.5" /> : "○"}
                  </span>
                  <span
                    className={`text-sm ${
                      done
                        ? "text-[var(--ink-muted)]"
                        : active
                          ? "text-[var(--ink)] font-medium"
                          : "text-[var(--ink-tertiary)]"
                    }`}
                  >
                    {STEP_META[step].title}
                    <span className="ml-2 text-[11px] text-[var(--ink-subtle)]">
                      {STEP_META[step].detail}
                    </span>
                  </span>
                </li>
              );
            })}
          </ol>
        </Panel>
      )}

      {repo && running && (
        <CodebasePanel
          codebase={null}
          loading
          repoLabel={REPO_OPTIONS.find((option) => option.value === repo)?.label}
        />
      )}

      {streamError && !running && (
        <div className="banner banner-amber no-print" role="alert">
          <span aria-hidden>⚠</span>
          <div className="flex flex-1 flex-wrap items-center justify-between gap-2">
            <div className="text-xs">
              <div className="font-medium">Estimate did not complete</div>
              <div className="opacity-90">{streamError}</div>
              <div className="opacity-80">
                Check the backend is running, then retry — nothing was stored.
              </div>
            </div>
            <button type="button" className="btn" onClick={runEstimate}>
              Retry
            </button>
          </div>
        </div>
      )}

      {!estimate && !running && (
        <Panel>
          <EmptyState
            title="No estimate yet"
            hint="Paste an email above and press Estimate — or pick one of the sample scenarios. Judges: the fastest path is Onboarding → Load sample data."
          />
        </Panel>
      )}

      {estimate && (
        <div className="space-y-5">
          {(estimate.warnings.length > 0 || extraNotes.length > 0) && (
            <div className="space-y-2">
              {[...estimate.warnings, ...extraNotes].map((warning) => (
                <div key={warning} className="banner banner-amber" role="alert">
                  <span aria-hidden>⚠</span>
                  <span className="text-xs">{warning}</span>
                </div>
              ))}
            </div>
          )}

          <div className="grid gap-5 xl:grid-cols-[minmax(0,1.55fr)_minmax(0,1fr)]">
            <Panel
              title={
                <span className="flex flex-wrap items-center gap-2">
                  Effort estimate <ModeBadge mode={estimate.estimate.mode} />{" "}
                  <MethodBadge
                    method={estimate.estimate.method}
                    unknownCount={unknownCount}
                  />
                </span>
              }
              subtitle="P10/P50/P90 in days — the range is the answer, not a single number."
              right={
                <div className="no-print flex gap-2">
                  <button
                    type="button"
                    className="btn border-[var(--hairline-strong)] bg-[var(--surface-1)] text-[var(--ink)] hover:border-[var(--primary)] hover:text-[var(--primary-hover)]"
                    onClick={copyQuestions}
                  >
                    {copied ? "✓ Copied" : "Copy questions for email"}
                  </button>
                  <button
                    type="button"
                    className="btn"
                    onClick={() => window.print()}
                  >
                    Print proposal
                  </button>
                </div>
              }
            >
              <EstimateChart
                estimate={estimate.estimate}
                projectsCount={health.data?.projects_count ?? null}
                similarCount={estimate.similar_projects.length}
                topScore={topScore}
              />
              {baseEstimate && answeredCount > 0 && (
                <div className="mt-4">
                  <RangeCompare
                    before={baseEstimate.estimate}
                    after={estimate.estimate}
                    unknownCount={unknownCount}
                    busy={answering}
                  />
                </div>
              )}
              {baseEstimate && answeredCount === 0 && baseQuestions.length > 0 && (
                <p className="mt-3 text-[11px] text-[var(--faint)]">
                  Answer the ranked questions (Có / Không) → this range is
                  re-estimated in place and a before/after comparison appears
                  here.
                </p>
              )}
            </Panel>

            <Panel
              title={
                <span className="flex items-center gap-2">
                  Ranked questions
                  <Term term="Value of Information" tip={GLOSSARY.voi}>
                    <span className="text-[10px] normal-case tracking-normal text-[var(--faint)]">
                      what is VoI?
                    </span>
                  </Term>
                </span>
              }
              subtitle="Ranked by impact; each Có/Không answer re-runs the estimate and resolves an unknown — the relative uncertainty narrows (a Yes that adds scope can widen the interval). Answering stores nothing."
            >
              <RankedQuestionsList
                questions={baseQuestions}
                answers={answers}
                onAnswer={(feature, value) => void applyAnswers(feature, value)}
                onClearAnswers={clearAnswers}
                busy={answering}
              />
              {answerError && (
                <div className="banner banner-red mt-3 no-print" role="alert">
                  <span aria-hidden>⚠</span>
                  <div className="flex-1 text-xs">
                    <div className="font-medium">Couldn&apos;t apply that answer</div>
                    <div className="opacity-90">{answerError}</div>
                    <div className="opacity-80">
                      The shown range keeps the last successful answers — check
                      the backend and try again.
                    </div>
                  </div>
                </div>
              )}
            </Panel>
          </div>

          {estimate.codebase && <CodebasePanel codebase={estimate.codebase} />}

          <Panel
            title="Extracted features (15)"
            subtitle="Every card carries confidence and a verbatim evidence quote — review before sending."
          >
            <FeatureGrid findings={estimate.findings} />
          </Panel>

          <div className="grid gap-5 xl:grid-cols-2">
            <Panel
              title="Similar past projects"
              subtitle="The evidence behind the estimate (hybrid keyword + similarity score)."
            >
              <SimilarProjectsList projects={estimate.similar_projects} />
            </Panel>
            <Panel
              title="Learned coefficients"
              subtitle="What the model learned from history — multiplier per feature."
            >
              <ContributionBar
                estimate={estimate.estimate}
                coefficients={estimate.coefficients}
                findings={estimate.findings}
              />
              <CoefficientsTable coefficients={estimate.coefficients} />
            </Panel>
          </div>

          <PackageBuilder
            email={estimateEmail || email}
            suggestedBudget={Math.max(1, Math.round(estimate.estimate.p50 * 0.9))}
          />

          <p className="text-[11px] text-[var(--faint)]">
            Method: Ridge regression on log(days) + conformal intervals. The LLM
            (provider: {health.data?.llm_provider ?? "unknown"}) only extracts
            features;{" "}
            <Term term="MAE" tip={GLOSSARY.mae}>
              accuracy
            </Term>{" "}
            and{" "}
            <Term term="Coverage" tip={GLOSSARY.coverage}>
              coverage
            </Term>{" "}
            are measured on the Proof screen. Demo data — see{" "}
            <span className="num">docs/API.md</span>.
          </p>
        </div>
      )}

      {estimate && (
        <ProposalPrintView
          estimate={estimate}
          emailExcerpt={
            email.trim().length > 600 ? `${email.trim().slice(0, 600)}…` : email.trim()
          }
          provider={health.data?.llm_provider ?? "unknown"}
          projectsCount={health.data?.projects_count ?? null}
          generatedAt={generatedAt}
        />
      )}
    </div>
  );
}
