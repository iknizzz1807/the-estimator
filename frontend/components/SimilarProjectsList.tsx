"use client";

import type { SimilarProject } from "@/lib/types";
import { featureLabel } from "@/lib/features";
import { fmtInt } from "@/lib/format";
import { EmptyState } from "./ui";

/** The 3 nearest historical projects that ground the estimate (spec §6.6). */
export function SimilarProjectsList({ projects }: { projects: SimilarProject[] }) {
  if (projects.length === 0) {
    return (
      <EmptyState
        title="No similar projects found"
        hint="History may be empty or too small — estimates fall back to wider intervals."
      />
    );
  }
  return (
    <div className="space-y-2.5">
      {projects.map((project) => (
        <article key={project.project_id} className="panel-2 p-3">
          <div className="flex items-start justify-between gap-2">
            <div className="min-w-0">
              <span className="num text-xs text-[var(--cyan)]">
                {project.project_id}
              </span>
              <p className="mt-0.5 text-sm leading-5 text-[var(--text)]">
                {project.title_hint}
              </p>
            </div>
            <span
              className="chip chip-info num shrink-0"
              title="Hybrid similarity score (0–1): the higher, the closer the match"
            >
              {project.score.toFixed(2)}
            </span>
          </div>
          <div className="mt-2 flex flex-wrap items-center gap-2 text-xs">
            <span className="num text-[var(--text)]">
              {fmtInt(project.actual_days)} days actual
            </span>
            <span className="text-[var(--faint)]">·</span>
            <span className="text-[var(--dim)]">
              {project.shared_features.length} shared feature
              {project.shared_features.length === 1 ? "" : "s"}
            </span>
          </div>
          {project.shared_features.length > 0 && (
            <div className="mt-2 flex flex-wrap gap-1">
              {project.shared_features.map((feature) => (
                <span key={feature} className="chip chip-ok">
                  {featureLabel(feature)}
                </span>
              ))}
            </div>
          )}
        </article>
      ))}
    </div>
  );
}
