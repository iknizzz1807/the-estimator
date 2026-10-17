"use client";

import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { useAsyncAction } from "@/lib/hooks";
import type { PackagesResponse, QuotePackage } from "@/lib/types";
import { featureLabel } from "@/lib/features";
import { fmtInt } from "@/lib/format";
import {
  EmptyState,
  ErrorState,
  Panel,
  SkeletonLines,
  Spinner,
} from "./ui";
import { PricingCurve } from "./PricingCurve";
import { GLOSSARY, Term } from "./Tooltip";

const TIER_ORDER: Record<string, number> = { core: 0, standard: 1, full: 2 };

function probabilityTone(probability: number | null): {
  text: string;
  bar: string;
  label: string;
  pill: string;
} {
  if (probability === null) {
    return {
      text: "text-[#8a8f98]",
      bar: "bg-[#23252a]",
      label: "—",
      pill: "border-[#23252a] bg-[#141516] text-[#8a8f98]",
    };
  }
  if (probability <= 0.25) {
    return {
      text: "text-[#27a644]",
      bar: "bg-[#27a644]",
      label: "comfortable",
      pill: "border-[rgba(39,166,68,0.3)] bg-[rgba(39,166,68,0.1)] text-[#27a644]",
    };
  }
  if (probability <= 0.5) {
    return {
      text: "text-[#f59e0b]",
      bar: "bg-[#f59e0b]",
      label: "risky",
      pill: "border-[rgba(245,158,11,0.3)] bg-[rgba(245,158,11,0.1)] text-[#f59e0b]",
    };
  }
  return {
    text: "text-[#eb5757]",
    bar: "bg-[#eb5757]",
    label: "likely over budget",
    pill: "border-[rgba(235,87,87,0.3)] bg-[rgba(235,87,87,0.1)] text-[#eb5757]",
  };
}

function PackageCard({
  pkg,
  recommended,
}: {
  pkg: QuotePackage;
  recommended: boolean;
}) {
  const risk = probabilityTone(pkg.over_budget_prob);
  const includedCount = Object.values(pkg.features_included).filter(
    (value) => value === 1
  ).length;

  return (
    <div
      className={`relative flex flex-col justify-between rounded-lg border p-5 sm:p-6 transition-all ${
        recommended
          ? "border-[#5e6ad2] bg-[#141516] shadow-[0_0_24px_rgba(94,106,210,0.12)]"
          : "border-[#23252a] bg-[#0f1011] hover:border-[#34343a] hover:bg-[#141516]"
      }`}
    >
      <div className="space-y-3.5">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <h3 className="text-base font-semibold text-[#f7f8f8]">
              {pkg.label}
            </h3>
            <span className="rounded-full border border-[#23252a] bg-[#18191a] px-2 py-0.5 font-mono text-[10.5px] uppercase tracking-wider text-[#8a8f98]">
              {pkg.tier}
            </span>
          </div>

          {recommended && (
            <span
              className="inline-flex items-center gap-1.5 rounded-full border border-[rgba(94,106,210,0.4)] bg-[rgba(94,106,210,0.15)] px-2.5 py-0.5 text-[11px] font-semibold text-[#828fff]"
              title="Most scope whose over-budget probability stays ≤ 25%"
            >
              <span className="h-1.5 w-1.5 rounded-full bg-[#5e6ad2]" />
              Recommended
            </span>
          )}
        </div>

        <div className="flex items-baseline gap-2">
          <span className="font-mono text-3xl font-bold tracking-tight text-[#f7f8f8]">
            {fmtInt(pkg.estimate.p50)}
          </span>
          <div className="text-xs text-[#8a8f98]">
            <span>days (P50)</span>
            <span className="mx-1 text-[#62666d]">·</span>
            <span className="font-mono tabular-nums text-[#62666d]">
              {fmtInt(pkg.estimate.p10)}–{fmtInt(pkg.estimate.p90)}d range
            </span>
          </div>
        </div>

        {/* Clean Linear Progress Indicator */}
        <div className="rounded-lg border border-[#23252a]/70 bg-[#0f1011]/80 p-3">
          <div className="flex items-center justify-between text-xs">
            <span className="text-[11px] uppercase tracking-wider text-[#8a8f98]">
              <Term term="Over-budget probability" tip={GLOSSARY.overBudget}>
                P(over budget)
              </Term>
            </span>
            <div className="flex items-center gap-1.5">
              <span className={`font-mono text-xs font-semibold tabular-nums ${risk.text}`}>
                {pkg.over_budget_prob === null
                  ? "—"
                  : `${Math.round(pkg.over_budget_prob * 100)}%`}
              </span>
              <span className={`rounded-full border px-1.5 py-0.2 text-[9.5px] font-medium tracking-wide ${risk.pill}`}>
                {risk.label}
              </span>
            </div>
          </div>

          <div className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-[#18191a]">
            <div
              className={`h-full transition-all duration-300 ${risk.bar}`}
              style={{
                width: `${Math.round((pkg.over_budget_prob ?? 0) * 100)}%`,
              }}
            />
          </div>
        </div>

        {pkg.excluded.length > 0 ? (
          <div className="space-y-1.5 text-xs text-[#8a8f98]">
            <div className="text-[11px] text-[#62666d]">
              Phased out ({pkg.excluded.length}):
            </div>
            <div className="flex flex-wrap gap-1">
              {pkg.excluded.map((feature) => (
                <span
                  key={feature}
                  className="inline-flex items-center rounded-full border border-[#23252a] bg-[#18191a] px-2 py-0.5 text-[11px] text-[#8a8f98]"
                  title={`${featureLabel(feature)} is deferred to a later phase in this tier`}
                >
                  {featureLabel(feature)}
                </span>
              ))}
            </div>
          </div>
        ) : (
          <div className="text-xs text-[#62666d]">
            Full requested scope — nothing phased out.
          </div>
        )}
      </div>

      <div className="mt-4 border-t border-[#23252a]/70 pt-3 text-[11px] text-[#62666d]">
        <span className="font-mono tabular-nums text-[#8a8f98]">
          {includedCount} of {Object.keys(pkg.features_included).length}
        </span>{" "}
        features included · {pkg.notes}
      </div>
    </div>
  );
}

/**
 * Budget-fit quote packages (contract v0.2, POST /api/packages): enter a
 * budget in days, get three scope tiers from the same model with an honest
 * over-budget probability and a recommendation.
 * Styled to Linear design language: Surface-1 cards (#0f1011), Surface-2 highlighted
 * recommended tier (#141516) with Linear lavender accent border (#5e6ad2),
 * and primary action buttons.
 */
export function PackageBuilder({
  email,
  suggestedBudget,
}: {
  email: string;
  /** Prefill for the budget input (typically ~90% of the current P50). */
  suggestedBudget?: number | null;
}) {
  const [budget, setBudget] = useState("");
  const [inputError, setInputError] = useState<string | null>(null);
  const [data, setData] = useState<PackagesResponse | null>(null);
  const initialized = useRef(false);
  const action = useAsyncAction((text: string, budgetDays: number) =>
    api.estimatePackages(text, budgetDays)
  );

  const trimmedEmail = email.trim();

  // Default budget derived from the estimate (a touch below P50 so the
  // over-budget math has something to say) — once, unless the user typed.
  useEffect(() => {
    if (!initialized.current && trimmedEmail.length > 0 && budget === "") {
      initialized.current = true;
      const fallback = suggestedBudget && suggestedBudget > 0 ? suggestedBudget : 30;
      setBudget(String(Math.max(1, Math.round(fallback))));
    }
  }, [trimmedEmail, budget, suggestedBudget]);

  // A new estimate invalidates previously built packages.
  useEffect(() => {
    setData(null);
    setInputError(null);
  }, [trimmedEmail]);

  const build = async () => {
    const days = Number(budget);
    if (!Number.isFinite(days) || days <= 0) {
      setInputError("Enter a budget in days greater than 0.");
      return;
    }
    setInputError(null);
    const result = await action.run(trimmedEmail, days);
    if (result) setData(result);
  };

  const packages = data
    ? [...data.packages].sort(
        (a, b) => (TIER_ORDER[a.tier] ?? 9) - (TIER_ORDER[b.tier] ?? 9)
      )
    : [];
  const recommended = data?.recommendation
    ? packages.find((pkg) => pkg.tier === data.recommendation)
    : undefined;

  return (
    <Panel
      id="packages"
      title="Quote packages — budget fit"
      subtitle="Three scope tiers from the same model: phase out optional capabilities until the scope fits the budget."
    >
      <div className="space-y-5">
        <div className="flex flex-wrap items-end gap-3 rounded-lg border border-[#23252a] bg-[#0f1011] p-4">
          <div>
            <label
              htmlFor="package-budget"
              className="mb-1.5 block text-[11px] font-medium uppercase tracking-[0.1em] text-[#8a8f98]"
            >
              Client budget (days)
            </label>
            <input
              id="package-budget"
              type="number"
              min={1}
              step={1}
              className="w-36 rounded-lg border border-[#23252a] bg-[#141516] px-3 py-1.5 font-mono text-sm tabular-nums text-[#f7f8f8] placeholder-[#62666d] transition-colors focus:border-[#5e6ad2] focus:outline-none focus:ring-1 focus:ring-[#5e69d1] disabled:opacity-50"
              value={budget}
              disabled={action.loading || trimmedEmail.length === 0}
              onChange={(event) => {
                setBudget(event.target.value);
                if (inputError) setInputError(null);
              }}
              onKeyDown={(event) => {
                if (event.key === "Enter") void build();
              }}
              placeholder="30"
            />
          </div>

          <button
            type="button"
            className="inline-flex items-center gap-2 rounded-md bg-[#5e6ad2] px-4 py-2 text-xs font-semibold text-white shadow-sm transition-colors hover:bg-[#828fff] disabled:cursor-not-allowed disabled:opacity-50"
            disabled={action.loading || trimmedEmail.length === 0}
            onClick={() => void build()}
          >
            {action.loading ? <Spinner className="h-3.5 w-3.5" /> : null}
            {action.loading ? "Building packages…" : "Build quote packages"}
          </button>

          {data && !action.loading && (
            <span className="font-mono text-xs tabular-nums text-[#8a8f98]">
              Budget: {fmtInt(data.budget_days ?? 0)} days · Method:{" "}
              <span className="text-[#f7f8f8]">{data.method ?? "—"}</span>
            </span>
          )}
        </div>

        {inputError && (
          <div
            className="flex items-center gap-2 rounded-lg border border-[rgba(235,87,87,0.3)] bg-[rgba(235,87,87,0.1)] px-3 py-2 text-xs text-[#eb5757]"
            role="alert"
          >
            <span aria-hidden>⚠</span>
            <span>{inputError}</span>
          </div>
        )}

        {trimmedEmail.length === 0 && (
          <EmptyState
            title="Packages need an estimate first"
            hint="Run an estimate above, then set the client's budget in days and build the three scope tiers."
          />
        )}

        {action.loading && (
          <div className="space-y-3" role="status" aria-live="polite">
            <div className="flex items-center gap-2 text-xs text-[#8a8f98]">
              <Spinner className="h-3.5 w-3.5" />
              Monte-Carlo intervals for three scope tiers + over-budget probabilities…
            </div>
            <SkeletonLines lines={4} />
          </div>
        )}

        {action.error && !action.loading && (
          <ErrorState
            title="Packages failed"
            message={action.error}
            onRetry={() => void build()}
            hint="POST /api/packages { email_text, budget_days } — check the backend and retry."
          />
        )}

        {!data && !action.loading && !action.error && trimmedEmail.length > 0 && (
          <EmptyState
            title="No packages built yet"
            hint="Set the client's budget in days and press Build quote packages — the recommendation keeps the widest scope whose over-budget risk stays ≤ 25%."
          />
        )}

        {data && !action.loading && (
          <div className="space-y-5">
            {data.recommendation_note && (
              <div
                className="flex items-center gap-2 rounded-lg border border-[rgba(245,158,11,0.3)] bg-[rgba(245,158,11,0.08)] px-3.5 py-2.5 text-xs text-[#f59e0b]"
                role="alert"
              >
                <span aria-hidden className="shrink-0 text-sm">⚠</span>
                <span>{data.recommendation_note}</span>
              </div>
            )}

            {/* Three Tier Cards */}
            <div className="grid gap-4 lg:grid-cols-3">
              {packages.map((pkg) => (
                <PackageCard
                  key={pkg.tier}
                  pkg={pkg}
                  recommended={
                    recommended !== undefined && pkg.tier === recommended.tier
                  }
                />
              ))}
            </div>

            {data.pricing && (
              <PricingCurve
                pricing={data.pricing}
                budgetDays={data.budget_days}
              />
            )}

            <p className="text-[11px] leading-relaxed text-[#62666d]">
              Over-budget probability comes from each tier&apos;s own P10/P50/P90
              (lognormal fit) — deterministic and seeded. Unknown features stay
              unknown in every tier, so the interval keeps its honest
              uncertainty. <span className="font-mono text-[#8a8f98]">POST /api/packages</span> is
              read-only: no project row is created.
            </p>
          </div>
        )}
      </div>
    </Panel>
  );
}
