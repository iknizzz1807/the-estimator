"use client";

import type { Coefficient } from "@/lib/types";
import { featureLabel } from "@/lib/features";
import { EmptyState } from "./ui";

/**
 * Learned multipliers (exp of the Ridge coefficients), top 3 highlighted.
 * The UI shows sample_count so every coefficient carries its evidence.
 */
export function CoefficientsTable({ coefficients }: { coefficients: Coefficient[] }) {
  if (coefficients.length === 0) {
    return (
      <EmptyState
        title="No coefficients yet"
        hint="Cold-start mode uses documented industry baselines until history exists."
      />
    );
  }
  const sorted = [...coefficients].sort((a, b) => b.multiplier - a.multiplier);
  const topThree = new Set(sorted.slice(0, 3).map((c) => c.feature));
  const maxMultiplier = sorted[0]?.multiplier ?? 1;

  return (
    <div className="overflow-auto">
      <table className="data-table">
        <thead>
          <tr>
            <th>Feature</th>
            <th title="Learned multiplicative effect on effort">Multiplier</th>
            <th title="Training samples behind this coefficient">Samples</th>
            <th className="w-1/3">Relative effect</th>
          </tr>
        </thead>
        <tbody>
          {sorted.map((coefficient) => (
            <tr key={coefficient.feature}>
              <td>
                <span className="flex items-center gap-2">
                  {topThree.has(coefficient.feature) && (
                    <span
                      className="h-1.5 w-1.5 rounded-full bg-[var(--primary)]"
                      title="Top 3 impact"
                    />
                  )}
                  {featureLabel(coefficient.feature)}
                </span>
              </td>
              <td className="num text-[var(--ink)] font-medium">
                ×{coefficient.multiplier.toFixed(2)}
              </td>
              <td className="num text-[var(--ink-subtle)]">{coefficient.sample_count}</td>
              <td>
                <div className="h-1.5 w-full overflow-hidden rounded-full bg-[var(--surface-3)] border border-[var(--hairline)]">
                  <div
                    className={
                      topThree.has(coefficient.feature)
                        ? "h-full bg-[var(--primary)]"
                        : "h-full bg-[var(--brand-secure)]"
                    }
                    style={{
                      width: `${Math.max(
                        4,
                        (coefficient.multiplier / maxMultiplier) * 100
                      )}%`,
                    }}
                  />
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="mt-2 text-[11px] text-[var(--faint)]">
        exp(Ridge coefficient) trained on log(days) · top 3 highlighted. A
        coefficient only moves when real actuals arrive.
      </p>
    </div>
  );
}
