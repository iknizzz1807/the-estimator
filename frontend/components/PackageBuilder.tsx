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
} {
  if (probability === null) {
    return { text: "text-[var(--dim)]", bar: "bg-[var(--border-strong)]", label: "—" };
  }
  if (probability <= 0.25) {
    return {
      text: "text-[var(--lime)]",
      bar: "bg-[var(--lime)]",
      label: "comfortable",
    };
  }
  if (probability <= 0.5) {
    return {
      text: "text-[var(--amber)]",
      bar: "bg-[var(--amber)]",
      label: "risky",
    };
  }
  return { text: "text-[var(--red)]", bar: "bg-[var(--red)]", label: "likely over budget" };
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
      className={`panel-2 flex flex-col gap-2 p-3 ${
        recommended
          ? "border-[rgba(163,230,53,0.55)] shadow-[0_0_18px_rgba(163,230,53,0.08)]"
          : ""
      }`}
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <span className="text-sm font-semibold text-[var(--text)]">
            {pkg.label}
          </span>
          <span className="chip chip-off num">{pkg.tier}</span>
        </div>
        {recommended && (
          <span className="chip chip-ok" title="Most scope whose over-budget probability stays ≤ 25%">
            ✓ recommended
          </span>
        )}
      </div>

      <div className="flex items-baseline gap-2">
        <span className="num text-2xl font-semibold text-[var(--text)]">
          {fmtInt(pkg.estimate.p50)}
        </span>
        <span className="text-xs text-[var(--dim)]">
          days (P50) · range {fmtInt(pkg.estimate.p10)}–{fmtInt(pkg.estimate.p90)}
        </span>
      </div>

      <div>
        <div className="flex items-center justify-between text-[11px]">
          <span className="text-[var(--dim)]">
            <Term term="Over-budget probability" tip={GLOSSARY.overBudget}>
              P(over budget)
            </Term>
          </span>
          <span className={`num ${risk.text}`}>
            {pkg.over_budget_prob === null
              ? "—"
              : `${Math.round(pkg.over_budget_prob * 100)}%`}
            <span className="ml-1.5 font-normal opacity-80">{risk.label}</span>
          </span>
        </div>
        <div className="mt-1 h-1.5 w-full overflow-hidden rounded-full bg-[#1a2637]">
          <div
            className={`h-full ${risk.bar}`}
            style={{
              width: `${Math.round((pkg.over_budget_prob ?? 0) * 100)}%`,
            }}
          />
        </div>
      </div>

      {pkg.excluded.length > 0 ? (
        <div className="text-[11px] text-[var(--dim)]">
          <div className="mb-1">Phased out ({pkg.excluded.length}):</div>
          <div className="flex flex-wrap gap-1">
            {pkg.excluded.map((feature) => (
              <span
                key={feature}
                className="chip chip-unknown"
                title={`${featureLabel(feature)} is deferred to a later phase in this tier`}
              >
                {featureLabel(feature)}
              </span>
            ))}
          </div>
        </div>
      ) : (
        <div className="text-[11px] text-[var(--faint)]">
          Nothing phased out — the full requested scope.
        </div>
      )}

      <p className="mt-auto text-[11px] leading-4 text-[var(--faint)]">
        {includedCount} of {Object.keys(pkg.features_included).length} features
        included · {pkg.notes}
      </p>
    </div>
  );
}

/**
 * Budget-fit quote packages (contract v0.2, POST /api/packages): enter a
 * budget in days, get three scope tiers from the same model with an honest
 * over-budget probability and a recommendation.
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
      <div className="space-y-4">
        <div className="flex flex-wrap items-end gap-3">
          <div>
            <label
              htmlFor="package-budget"
              className="mb-1 block text-[11px] uppercase tracking-[0.1em] text-[var(--dim)]"
            >
              Client budget (days)
            </label>
            <input
              id="package-budget"
              type="number"
              min={1}
              step={1}
              className="input num w-36"
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
            className="btn btn-primary"
            disabled={action.loading || trimmedEmail.length === 0}
            onClick={() => void build()}
          >
            {action.loading ? <Spinner className="h-3.5 w-3.5" /> : null}
            {action.loading ? "Building packages…" : "Build quote packages"}
          </button>
          {data && !action.loading && (
            <span className="text-[11px] text-[var(--faint)]">
              built for a {fmtInt(data.budget_days ?? 0)}-day budget · method:{" "}
              <span className="num">{data.method ?? "—"}</span>
            </span>
          )}
        </div>

        {inputError && (
          <div className="banner banner-red" role="alert">
            <span aria-hidden>⚠</span>
            <span className="text-xs">{inputError}</span>
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
            <div className="flex items-center gap-2 text-xs text-[var(--dim)]">
              <Spinner className="h-3.5 w-3.5" />
              Monte-Carlo intervals for three scope tiers + over-budget
              probabilities…
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
          <div className="space-y-3">
            {data.recommendation_note && (
              <div className="banner banner-amber" role="alert">
                <span aria-hidden>⚠</span>
                <span className="text-xs">{data.recommendation_note}</span>
              </div>
            )}

            <div className="grid gap-3 lg:grid-cols-3">
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

            <p className="text-[11px] leading-5 text-[var(--faint)]">
              Over-budget probability comes from each tier&apos;s own P10/P50/P90
              (lognormal fit) — deterministic and seeded. Unknown features stay
              unknown in every tier, so the interval keeps its honest
              uncertainty. <span className="num">POST /api/packages</span> is
              read-only: no project row is created.
            </p>
          </div>
        )}
      </div>
    </Panel>
  );
}
