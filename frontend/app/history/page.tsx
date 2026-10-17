"use client";

import { useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import { useAsyncData } from "@/lib/hooks";
import type { ProjectRow } from "@/lib/types";
import { fmtNum } from "@/lib/format";
import { HistoryTable } from "@/components/HistoryTable";
import { ActualsModal } from "@/components/ActualsModal";
import { EmptyState, ErrorState, Panel, SkeletonLines, StatCard } from "@/components/ui";

export default function HistoryPage() {
  const { data, loading, error, reload } = useAsyncData(() => api.projects());
  const [selected, setSelected] = useState<ProjectRow | null>(null);

  const rows = data ?? [];
  const doneRows = rows.filter((row) => row.status === "done");
  const openRows = rows.filter((row) => row.status !== "done");
  const deltas = doneRows
    .map((row) => row.delta_pct)
    .filter((value): value is number => value !== null && value !== undefined);
  const meanAbsDelta =
    deltas.length > 0
      ? deltas.reduce((acc, value) => acc + Math.abs(value), 0) / deltas.length
      : null;

  return (
    <div className="space-y-5">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight text-[var(--ink)]">Project history</h1>
        <p className="mt-1 text-sm text-[var(--ink-subtle)]">
          Estimates vs reality. Enter actuals on finished projects — every entry
          becomes a training sample and moves the coefficients.
        </p>
      </header>

      {loading && !data && (
        <Panel>
          <SkeletonLines lines={6} />
        </Panel>
      )}

      {error && !data && (
        <Panel>
          <ErrorState
            title="Could not load projects"
            message={error}
            onRetry={reload}
            hint="The table is fed by GET /api/projects — start the backend with scripts/run_api.sh."
          />
        </Panel>
      )}

      {data && rows.length === 0 && (
        <Panel>
          <EmptyState
            title="No projects yet"
            hint="Import a CSV or load sample data from Onboarding to build history before estimating."
          >
            <Link href="/" className="btn btn-primary mt-1">
              Go to Onboarding →
            </Link>
          </EmptyState>
        </Panel>
      )}

      {data && rows.length > 0 && (
        <>
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <StatCard
              label="Projects"
              value={rows.length}
              sub="rows in history"
            />
            <StatCard
              label="Completed"
              value={doneRows.length}
              tone="lime"
              sub="have actuals (training samples)"
            />
            <StatCard
              label="Awaiting actuals"
              value={openRows.length}
              tone="amber"
              sub="in progress or pending"
            />
            <StatCard
              label="Mean |Δ%|"
              value={meanAbsDelta === null ? "—" : fmtNum(meanAbsDelta, 1)}
              unit={meanAbsDelta === null ? undefined : "%"}
              sub={
                deltas.length > 0
                  ? `across ${deltas.length} completed projects (vs system P50)`
                  : "no completed projects yet"
              }
            />
          </div>

          <Panel
            title="All projects"
            subtitle="Filters: status, feature, date range — Δ% colours follow the review thresholds."
          >
            <HistoryTable rows={rows} onEnterActual={setSelected} />
          </Panel>

          <p className="text-[11px] text-[var(--faint)]">
            Accuracy trend and coverage live on the{" "}
            <Link href="/proof" className="text-[var(--primary)] hover:underline font-medium">
              Proof
            </Link>{" "}
            screen. Mean |Δ%| here is the raw average of entered actuals.
          </p>
        </>
      )}

      {selected && (
        <ActualsModal
          row={selected}
          onClose={() => setSelected(null)}
          onSaved={() => void reload()}
        />
      )}
    </div>
  );
}
