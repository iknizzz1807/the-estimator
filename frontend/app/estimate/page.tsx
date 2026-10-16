"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { api, estimateStream } from "@/lib/api";
import { errMessage, useAsyncData } from "@/lib/hooks";
import { readPrefillEmail, readStoredEstimate } from "@/lib/session";
import { STREAM_STEPS, type EstimateResponse, type StreamEvent } from "@/lib/types";
import { fmtInt, humanDuration } from "@/lib/format";
import { EmailInput } from "@/components/EmailInput";
import { ScenarioPicker } from "@/components/ImportCSVModal";
import { EstimateChart, ModeBadge } from "@/components/EstimateChart";
import { FeatureGrid } from "@/components/FeatureCard";
import { SimilarProjectsList } from "@/components/SimilarProjectsList";
import {
  RankedQuestionsList,
  formatQuestions,
} from "@/components/RankedQuestionsList";
import { CoefficientsTable } from "@/components/CoefficientsTable";
import { ProposalPrintView } from "@/components/ProposalPrintView";
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
  const [durationMs, setDurationMs] = useState<number | null>(null);
  const [generatedAt, setGeneratedAt] = useState("");
  const abortRef = useRef<AbortController | null>(null);

  const health = useAsyncData(() => api.health());
  const scenarios = useAsyncData(() => api.scenarios());

  // Landing-page handoff (scenario loaded → populated view) + cold-start link.
  useEffect(() => {
    const stored = readStoredEstimate();
    if (stored) {
      setEstimate(stored.estimate);
      setScenarioTitle(stored.scenarioTitle ?? null);
      setCompletedSteps([...STREAM_STEPS]);
    }
    const prefill = readPrefillEmail();
    if (prefill) setEmail(prefill);
    setColdNote(new URLSearchParams(window.location.search).get("cold") === "1");
    setGeneratedAt(new Date().toLocaleString());
  }, []);

  const runEstimate = async () => {
    const text = email.trim();
    if (!text) {
      setValidationError("Please paste the client email before estimating.");
      return;
    }
    setValidationError(null);
    setStreamError(null);
    setEstimate(null);
    setScenarioTitle(null);
    setDurationMs(null);
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
          setCompletedSteps([...STREAM_STEPS]);
          setActiveStep(null);
          setDurationMs(performance.now() - startedAt);
        } else if (event.type === "error") {
          setStreamError(event.message ?? "Estimation failed — please retry.");
          setActiveStep(null);
        }
      }, controller.signal);
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
    const notes: string[] = [];
    if (map.get("realtime_ui") === 1 && map.get("offline_mode") === 1) {
      notes.push(
        "Conflicting requirements flagged for review: real-time UI and offline mode are both present."
      );
    }
    if (
      estimate.findings.length > 0 &&
      estimate.findings.every((f) => f.value === null) &&
      !estimate.warnings.some((w) => /no features/i.test(w))
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
      window.setTimeout(() => setCopied(false), 2500);
    } catch {
      setStreamError("Clipboard is blocked here — use Copy all in the questions panel.");
    }
  };

  const topScore = estimate?.similar_projects[0]?.score ?? null;

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
                {estimate.project_id}
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
                        ? "border-[rgba(163,230,53,0.6)] text-[var(--lime)]"
                        : active
                          ? "border-[rgba(34,211,238,0.6)] text-[var(--cyan)]"
                          : "border-[var(--border)] text-[var(--faint)]"
                    }`}
                  >
                    {done ? "✓" : active ? <Spinner className="h-2.5 w-2.5" /> : "○"}
                  </span>
                  <span
                    className={`text-sm ${
                      done
                        ? "text-[var(--dim)]"
                        : active
                          ? "text-[var(--text)]"
                          : "text-[var(--faint)]"
                    }`}
                  >
                    {STEP_META[step].title}
                    <span className="ml-2 text-[11px] text-[var(--faint)]">
                      {STEP_META[step].detail}
                    </span>
                  </span>
                </li>
              );
            })}
          </ol>
        </Panel>
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
              title={<span className="flex items-center gap-2">Effort estimate <ModeBadge mode={estimate.estimate.mode} /></span>}
              subtitle="P10/P50/P90 in days — the range is the answer, not a single number."
              right={
                <div className="no-print flex gap-2">
                  <button type="button" className="btn btn-lime" onClick={copyQuestions}>
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
              subtitle="Ranked by impact; each answer can shift the P50 by the shown amount."
            >
              <RankedQuestionsList questions={estimate.questions} />
            </Panel>
          </div>

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
              <CoefficientsTable coefficients={estimate.coefficients} />
            </Panel>
          </div>

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
