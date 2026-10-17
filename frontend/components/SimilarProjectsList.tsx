"use client";

import type { SimilarProject } from "@/lib/types";
import { featureLabel } from "@/lib/features";
import { fmtInt } from "@/lib/format";
import { EmptyState } from "./ui";

/**
 * The 3 nearest historical projects that ground the estimate (spec §6.6).
 * Styled to Linear design language: Surface-1 cards (#0f1011), hairline borders (#23252a),
 * tabular typography (#f7f8f8, #8a8f98), and Linear lavender accents.
 */
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
    <div className="space-y-3">
      {projects.map((project) => (
        <article
          key={project.project_id}
          className="group rounded-lg border border-[#23252a] bg-[#0f1011] p-4 transition-colors hover:border-[#34343a] hover:bg-[#141516]"
        >
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                <span className="font-mono text-xs font-medium text-[#5e6ad2]">
                  {project.project_id}
                </span>
                <span className="text-[11px] text-[#62666d]">·</span>
                <span className="font-mono text-xs tabular-nums text-[#8a8f98]">
                  <strong className="font-semibold text-[#f7f8f8]">{fmtInt(project.actual_days)}</strong> days actual
                </span>
              </div>
              <p className="mt-1.5 text-sm font-medium leading-snug text-[#f7f8f8]">
                {project.title_hint}
              </p>
            </div>

            <div
              className="inline-flex shrink-0 items-center gap-1 rounded-full border border-[#23252a] bg-[#141516] px-2 py-0.5 font-mono text-[11px] tabular-nums text-[#d0d6e0]"
              title="Hybrid similarity score (0–1): the higher, the closer the match"
            >
              <span className="text-[9px] uppercase tracking-wider text-[#62666d]">Match</span>
              <span className="font-semibold text-[#5e6ad2]">{project.score.toFixed(2)}</span>
            </div>
          </div>

          <div className="mt-3 flex items-center gap-2 border-t border-[#23252a]/60 pt-2.5 text-xs text-[#8a8f98]">
            <span className="text-[11px] text-[#62666d]">
              {project.shared_features.length} shared feature
              {project.shared_features.length === 1 ? "" : "s"}:
            </span>
            {project.shared_features.length > 0 ? (
              <div className="flex flex-wrap gap-1.5">
                {project.shared_features.map((feature) => (
                  <span
                    key={feature}
                    className="inline-flex items-center rounded-full border border-[#23252a] bg-[#141516] px-2 py-0.5 text-[11px] text-[#d0d6e0] transition-colors group-hover:border-[#34343a]"
                  >
                    {featureLabel(feature)}
                  </span>
                ))}
              </div>
            ) : (
              <span className="text-[11px] text-[#62666d]">None detected</span>
            )}
          </div>
        </article>
      ))}
    </div>
  );
}
