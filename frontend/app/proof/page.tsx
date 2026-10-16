"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useAsyncAction, useAsyncData } from "@/lib/hooks";
import type { ABResponse, ReplayResponse } from "@/lib/types";
import { fmtInt, fmtNum, fmtPct, humanDuration } from "@/lib/format";
import { ReplayChart } from "@/components/ReplayChart";
import { ABComparisonTable } from "@/components/ABComparisonTable";
import {
  EmptyState,
  ErrorState,
  Panel,
  SkeletonLines,
  Spinner,
  StatCard,
} from "@/components/ui";
import { GLOSSARY, Term } from "@/components/Tooltip";

function CoverageBand({ coverage }: { coverage: number }) {
  const clamped = Math.max(0, Math.min(100, coverage));
  const inBand = clamped >= 75 && clamped <= 85;
  return (
    <div>
      <div className="relative h-6">
        <div className="absolute inset-x-0 top-1/2 h-2 -translate-y-1/2 rounded-full bg-[#18243a]" />
        <div
          className="absolute top-1/2 h-2 -translate-y-1/2 rounded-full border border-[rgba(163,230,53,0.6)] bg-[rgba(163,230,53,0.18)]"
          style={{ left: "75%", width: "10%" }}
          title="Target band 75–85%"
        />
        <div
          className={`absolute top-1/2 h-3.5 w-1 -translate-y-1/2 rounded ${
            inBand ? "bg-[var(--lime)]" : "bg-[var(--amber)]"
          }`}
          style={{ left: `${clamped}%` }}
          title={`Observed coverage ${fmtPct(clamped)}`}
        />
      </div>
      <div className="mt-1 flex justify-between text-[10px] text-[var(--faint)]">
        <span>0%</span>
        <span className="text-[var(--lime)]">target 75–85%</span>
        <span>100%</span>
      </div>
    </div>
  );
}

/**
 * In-band counts "+ 33/42 (78.6%)" — shown when the summary carries n_steps
 * (contract v0.2); falls back to nothing on older payloads.
 */
function CoverageCounts({
  summary,
  steps,
}: {
  summary: ReplayResponse["summary"];
  steps: ReplayResponse["steps"];
}) {
  const nSteps = summary.n_steps;
  if (typeof nSteps !== "number" || nSteps <= 0) return null;
  const inBand =
    steps.length === nSteps
      ? steps.filter((step) => step.in_interval).length
      : Math.round((summary.coverage_pct / 100) * nSteps);
  return (
    <div
      className="num mt-1 text-[11px] text-[var(--dim)]"
      title="Projects whose actual duration fell inside the predicted [P10, P90]"
    >
      + {inBand}/{nSteps} ({fmtPct(summary.coverage_pct)})
    </div>
  );
}

export default function ProofPage() {
  const health = useAsyncData(() => api.health());
  const scenarios = useAsyncData(() => api.scenarios());
  const [replay, setReplay] = useState<ReplayResponse | null>(null);
  const [replayMs, setReplayMs] = useState<number | null>(null);
  const [ab, setAb] = useState<ABResponse | null>(null);
  const [abEmail, setAbEmail] = useState("");
  const [abInitialized, setAbInitialized] = useState(false);

  const replayAction = useAsyncAction(async () => api.replay(10));
  const abAction = useAsyncAction(async (emailText: string) => api.ab(emailText, 10));

  // Pre-fill the A/B email with the first sample scenario (one-click demo).
  useEffect(() => {
    if (!abInitialized && scenarios.data && scenarios.data.length > 0) {
      setAbEmail(scenarios.data[0].email_text);
      setAbInitialized(true);
    }
  }, [scenarios.data, abInitialized]);

  const runReplay = async () => {
    const startedAt = performance.now();
    const result = await replayAction.run();
    if (result) {
      setReplay(result);
      setReplayMs(performance.now() - startedAt);
    }
  };

  const runAb = async () => {
    const text = abEmail.trim();
    if (!text) return;
    const result = await abAction.run(text);
    if (result) setAb(result);
  };

  const provider = health.data?.llm_provider ?? "unknown";

  return (
    <div className="space-y-5">
      <header>
        <h1 className="text-xl font-semibold">Proof — it learns</h1>
        <p className="mt-0.5 max-w-3xl text-xs leading-5 text-[var(--dim)]">
          Walk-forward replay trains on every prefix of history and predicts the
          next project ({""}
          <Term term="MAE" tip={GLOSSARY.mae}>
            MAE
          </Term>{" "}
          and{" "}
          <Term term="Coverage" tip={GLOSSARY.coverage}>
            coverage
          </Term>
          ), then an A/B check runs the same email through LLM-only estimation
          to expose run-to-run variance. This is the difference between a
          statistics engine and an LLM wrapper.
        </p>
      </header>

      <Panel
        title="Replay history"
        subtitle="Train on projects 1..i-1 → predict project i. Lower MAE and coverage near 80% = calibrated."
        right={
          <button
            type="button"
            className="btn btn-primary"
            disabled={replayAction.loading}
            onClick={runReplay}
          >
            {replayAction.loading ? <Spinner className="h-3.5 w-3.5" /> : null}
            {replayAction.loading ? "Replaying…" : replay ? "Run again" : "Run Replay"}
          </button>
        }
      >
        {!replay && !replayAction.loading && (
          <EmptyState
            title="Replay not run yet"
            hint="One click walks the model forward across all historical projects — a few seconds on the demo dataset."
          />
        )}

        {replayAction.loading && (
          <div className="space-y-3" role="status" aria-live="polite">
            <div className="flex items-center gap-2 text-xs text-[var(--dim)]">
              <Spinner className="h-3.5 w-3.5" />
              Walking forward across history — training on each prefix, then
              predicting the next project…
            </div>
            <SkeletonLines lines={5} />
          </div>
        )}

        {replayAction.error && !replayAction.loading && (
          <ErrorState
            title="Replay failed"
            message={replayAction.error}
            onRetry={runReplay}
            hint="GET /api/replay?min_train=10 — start the backend with scripts/run_api.sh."
          />
        )}

        {replay && !replayAction.loading && (
          <div className="space-y-4">
            <div className="grid gap-3 lg:grid-cols-4">
              <StatCard
                label={
                  <Term term="System MAE" tip={GLOSSARY.mae}>
                    System MAE
                  </Term>
                }
                value={fmtNum(replay.summary.mae_system, 1)}
                unit="days"
                tone="cyan"
                sub={`improvement vs team: ${fmtNum(
                  replay.summary.mae_team - replay.summary.mae_system,
                  1
                )} d`}
              />
              <StatCard
                label="Team MAE"
                value={fmtNum(replay.summary.mae_team, 1)}
                unit="days"
                tone="dim"
                sub="baseline: human estimates"
              />
              <StatCard
                label={
                  <span className="flex items-center gap-1.5">
                    LLM-only MAE
                    {replay.summary.llm_only_mode === "simulated" && (
                      <span className="chip chip-unknown">simulated</span>
                    )}
                  </span>
                }
                value={fmtNum(replay.summary.mae_llm_only, 1)}
                unit="days"
                tone="amber"
                sub={
                  replay.summary.llm_only_mode === "simulated"
                    ? "stub provider — variance emulated"
                    : "same emails via a raw LLM"
                }
              />
              <div className="panel-2 p-3">
                <div className="text-[11px] uppercase tracking-[0.1em] text-[var(--dim)]">
                  Coverage (in [P10, P90])
                </div>
                <div
                  className={`num mt-1 text-2xl font-semibold ${
                    replay.summary.coverage_pct >= 75 &&
                    replay.summary.coverage_pct <= 85
                      ? "text-[var(--lime)]"
                      : "text-[var(--amber)]"
                  }`}
                >
                  {fmtPct(replay.summary.coverage_pct)}
                </div>
                <CoverageCounts
                  summary={replay.summary}
                  steps={replay.steps}
                />
                <div className="mt-2">
                  <CoverageBand coverage={replay.summary.coverage_pct} />
                </div>
              </div>
            </div>

            <ReplayChart steps={replay.steps} summary={replay.summary} />

            <div>
              <div className="mb-1.5 flex items-center justify-between">
                <h3 className="text-xs uppercase tracking-[0.1em] text-[var(--dim)]">
                  Step detail ({replay.steps.length} walk-forward steps)
                </h3>
                {replayMs !== null && (
                  <span className="num text-[11px] text-[var(--faint)]">
                    computed in {humanDuration(replayMs)}
                  </span>
                )}
              </div>
              <div className="max-h-[320px] overflow-auto rounded-lg border border-[var(--border)]">
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>#</th>
                      <th>Project</th>
                      <th>P10</th>
                      <th>P50</th>
                      <th>P90</th>
                      <th>Actual</th>
                      <th title="Did the actual fall inside [P10, P90]?">In interval</th>
                    </tr>
                  </thead>
                  <tbody>
                    {replay.steps.map((step) => (
                      <tr key={`${step.i}-${step.project_id}`}>
                        <td className="num text-[var(--faint)]">{step.i}</td>
                        <td className="num text-[var(--text)]">{step.project_id}</td>
                        <td className="num text-[var(--dim)]">{fmtInt(step.p10)}</td>
                        <td className="num text-[var(--text)]">{fmtInt(step.p50)}</td>
                        <td className="num text-[var(--dim)]">{fmtInt(step.p90)}</td>
                        <td className="num text-[var(--text)]">{fmtInt(step.actual)}</td>
                        <td
                          className={step.in_interval ? "text-[var(--lime)]" : "text-[var(--red)]"}
                          title={
                            step.in_interval
                              ? "Actual inside the predicted range"
                              : "Actual outside the predicted range — counted in the 20% miss budget"
                          }
                        >
                          {step.in_interval ? "✓" : "✗"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        )}
      </Panel>

      <Panel
        title="A/B — same email, LLM-only ×10"
        subtitle={`Exposes run-to-run variance of a raw LLM — plus the fair "LLM + company history" strawman (contract v0.2). Current provider: ${provider}${
          provider === "stub" ? " (offline — variance simulated and labelled)" : ""
        }.`}
        right={
          <button
            type="button"
            className="btn btn-primary"
            disabled={abAction.loading || abEmail.trim().length === 0}
            onClick={runAb}
          >
            {abAction.loading ? <Spinner className="h-3.5 w-3.5" /> : null}
            {abAction.loading ? "Running 10×…" : "Run A/B (10 LLM-only runs)"}
          </button>
        }
      >
        <div className="space-y-3">
          <div>
            <div className="mb-1 flex items-end justify-between">
              <label
                htmlFor="ab-email"
                className="text-xs uppercase tracking-[0.1em] text-[var(--dim)]"
              >
                Email under test
              </label>
              <button
                type="button"
                className="btn"
                disabled={!scenarios.data?.length}
                onClick={() => {
                  if (scenarios.data?.[0]) setAbEmail(scenarios.data[0].email_text);
                }}
              >
                Use sample email
              </button>
            </div>
            <textarea
              id="ab-email"
              className="textarea"
              style={{ minHeight: 110 }}
              value={abEmail}
              onChange={(event) => setAbEmail(event.target.value)}
              placeholder="Paste the email to test run-to-run variance on…"
            />
          </div>

          {abAction.error && (
            <ErrorState
              title="A/B run failed"
              message={abAction.error}
              onRetry={runAb}
              hint="POST /api/ab { email_text, n: 10 } — check the backend and retry."
            />
          )}

          {abAction.loading && <SkeletonLines lines={4} />}

          {!ab && !abAction.loading && !abAction.error && (
            <EmptyState
              title="A/B not run yet"
              hint="The system number is deterministic; a raw LLM is not. This panel makes the difference visible."
            />
          )}

          {ab && !abAction.loading && <ABComparisonTable data={ab} />}
        </div>
      </Panel>
    </div>
  );
}
