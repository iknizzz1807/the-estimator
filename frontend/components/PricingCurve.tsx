"use client";

import { useEffect, useMemo, useState } from "react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip as ChartTooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { PricingBlock, PricingCurvePoint } from "@/lib/types";
import { fmtInt, fmtNum } from "@/lib/format";
import { Chip } from "./ui";
import { Term } from "./Tooltip";

/** Standard normal CDF (Zelen & Severo; |error| < 7.5e-8), parity with the backend. */
function normalCdf(z: number): number {
  const t = 1 / (1 + 0.2316419 * Math.abs(z));
  const density = 0.3989422804014327 * Math.exp((-z * z) / 2);
  const tail =
    density *
    t *
    (0.319381530 +
      t *
        (-0.356563782 +
          t * (1.781477937 + t * (-1.821255978 + t * 1.330274429))));
  return z >= 0 ? 1 - tail : tail;
}

/**
 * P(actual > quote) under the same lognormal fit the backend uses for each
 * tier's `over_budget_prob` (packages.py::_over_budget_prob): continuous, so
 * the slider readout stays exact even between two curve points.
 */
function overrunProbability(pricing: PricingBlock, days: number): number {
  const { p10, p50, p90 } = pricing;
  if (!(days > 0 && p10 > 0 && p90 > p10 && p50 > 0)) {
    return days < p50 ? 1 : 0;
  }
  const sigma = (Math.log(p90) - Math.log(p10)) / (2 * 1.2816);
  const z = (Math.log(days) - Math.log(p50)) / sigma;
  return Math.min(0.999, Math.max(0.001, 1 - normalCdf(z)));
}

function riskTone(risk: number): { text: string; stroke: string; label: string } {
  if (risk <= 0.25) {
    return { text: "text-[var(--lime)]", stroke: "var(--lime)", label: "comfortable" };
  }
  if (risk <= 0.5) {
    return { text: "text-[var(--amber)]", stroke: "var(--amber)", label: "risky" };
  }
  return { text: "text-[var(--red)]", stroke: "var(--red)", label: "likely to overrun" };
}

function CurveTooltip({
  active,
  payload,
}: {
  active?: boolean;
  payload?: Array<{ payload?: PricingCurvePoint }>;
}) {
  const point = payload?.[0]?.payload;
  if (!active || !point) return null;
  return (
    <div className="panel-2 px-2.5 py-2 text-[11px] shadow-lg">
      <div className="num text-[var(--text)]">{fmtNum(point.days, 1)} days quoted</div>
      <div className="num mt-1 text-[var(--cyan)]">
        {fmtNum(point.over_prob * 100, 1)}% overrun risk
      </div>
    </div>
  );
}

/**
 * Interactive pricing curve (contract v0.2 `pricing` block, fitted from the
 * Full-scope interval): drag the quote slider over the curve to read the
 * overrun risk + implied margin, or jump to the smallest ≤25% / ≤10% quotes.
 */
export function PricingCurve({
  pricing,
  budgetDays,
}: {
  pricing: PricingBlock;
  /** The client budget the packages were built for (slider default). */
  budgetDays?: number | null;
}) {
  const curve = pricing.curve;
  const curveMin = curve.length > 0 ? curve[0].days : Math.max(1, pricing.p10 * 0.6);
  const curveMax =
    curve.length > 0 ? curve[curve.length - 1].days : Math.max(2, pricing.p90 * 1.5);

  const sliderMin = Math.max(1, Math.floor(curveMin));
  const sliderMax = Math.max(sliderMin + 1, Math.ceil(curveMax));
  const clampQuote = (value: number) =>
    Math.min(sliderMax, Math.max(sliderMin, Math.round(value)));

  // Default: the customer budget when it falls on the curve, else P50.
  const defaultQuote = useMemo(() => {
    const wanted = budgetDays && budgetDays > 0 ? budgetDays : pricing.p50;
    return clampQuote(wanted);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [budgetDays, pricing.p50, sliderMin, sliderMax]);

  const [quote, setQuote] = useState<number>(defaultQuote);

  // A rebuilt package set (new curve / budget) resets the slider default.
  useEffect(() => {
    setQuote(defaultQuote);
  }, [defaultQuote]);

  const risk = useMemo(() => overrunProbability(pricing, quote), [pricing, quote]);
  const tone = riskTone(risk);
  const marginPct = pricing.p50 > 0 ? ((quote - pricing.p50) / pricing.p50) * 100 : 0;

  if (curve.length === 0) return null;

  const minRisk = overrunProbability(pricing, sliderMin);
  const maxRisk = overrunProbability(pricing, sliderMax);

  return (
    <div className="panel-2 space-y-3 p-3 sm:p-4" id="pricing-curve">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="text-[11px] font-semibold uppercase tracking-[0.1em] text-[var(--dim)]">
          Pricing curve — if I quote X days, what&apos;s my overrun risk?
        </div>
        <span className="chip chip-off num" title={`Fitted from the ${pricing.scope}-scope interval`}>
          {pricing.scope} scope · P10–P90 {fmtInt(pricing.p10)}–{fmtInt(pricing.p90)}d
        </span>
      </div>

      <div
        className="flex flex-wrap items-baseline gap-x-3 gap-y-1"
        aria-live="polite"
        role="status"
      >
        <span className="num text-lg text-[var(--text)]">
          Quote {fmtInt(quote)} days
        </span>
        <span aria-hidden className="text-[var(--faint)]">
          →
        </span>
        <span className={`num text-3xl font-semibold ${tone.text}`}>
          {Math.round(risk * 100)}%
        </span>
        <span className="text-sm text-[var(--dim)]">
          overrun risk <span className="opacity-80">({tone.label})</span>
        </span>
        <Chip
          tone={marginPct >= 0 ? "info" : "unknown"}
          title="(quote − P50) ÷ P50 — the buffer priced into this quote"
        >
          <span className="num">
            margin {marginPct >= 0 ? "+" : ""}
            {fmtNum(marginPct, 1)}% vs P50
          </span>
        </Chip>
      </div>

      <div>
        <input
          type="range"
          min={sliderMin}
          max={sliderMax}
          step={1}
          value={quote}
          onChange={(event) => setQuote(Number(event.target.value))}
          className="w-full cursor-pointer"
          style={{ accentColor: tone.stroke }}
          aria-label="Quote days"
          aria-valuetext={`${fmtInt(quote)} days, ${Math.round(risk * 100)}% overrun risk`}
        />
        <div className="flex justify-between text-[10px] text-[var(--faint)]">
          <span className="num">
            {fmtInt(sliderMin)}d · {Math.round(minRisk * 100)}% risk
          </span>
          <span className="num">
            {fmtInt(sliderMax)}d · {Math.round(maxRisk * 100)}% risk
          </span>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-2 text-[11px]">
        <span className="text-[var(--faint)]">Safe quotes:</span>
        <button
          type="button"
          className="chip chip-ok num cursor-pointer transition-opacity hover:opacity-80"
          title="Smallest quote keeping the overrun risk at or below 25%"
          onClick={() => setQuote(clampQuote(pricing.safe_quote_25))}
        >
          ≤25% risk → {fmtInt(pricing.safe_quote_25)}d
        </button>
        <button
          type="button"
          className="chip chip-ok num cursor-pointer transition-opacity hover:opacity-80"
          title="Smallest quote keeping the overrun risk at or below 10%"
          onClick={() => setQuote(clampQuote(pricing.safe_quote_10))}
        >
          ≤10% risk → {fmtInt(pricing.safe_quote_10)}d
        </button>
        <span className="text-[var(--faint)]">click to jump the slider</span>
      </div>

      <ResponsiveContainer width="100%" height={190}>
        <AreaChart data={curve} margin={{ top: 8, right: 14, bottom: 0, left: -8 }}>
          <defs>
            <linearGradient id="pricingRiskFill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="var(--cyan)" stopOpacity={0.35} />
              <stop offset="100%" stopColor="var(--cyan)" stopOpacity={0.02} />
            </linearGradient>
          </defs>
          <CartesianGrid stroke="var(--border)" strokeDasharray="3 6" />
          <XAxis
            dataKey="days"
            type="number"
            domain={["dataMin", "dataMax"]}
            tick={{ fill: "var(--faint)", fontSize: 10 }}
            stroke="var(--border)"
            tickFormatter={(value: number) => fmtInt(value)}
            label={{
              value: "quote (days)",
              position: "insideBottomRight",
              offset: -2,
              fill: "var(--faint)",
              fontSize: 10,
            }}
          />
          <YAxis
            domain={[0, 1]}
            tick={{ fill: "var(--faint)", fontSize: 10 }}
            stroke="var(--border)"
            tickFormatter={(value: number) => `${Math.round(value * 100)}%`}
            width={44}
          />
          <ChartTooltip content={<CurveTooltip />} />
          <ReferenceLine
            y={0.25}
            stroke="var(--lime)"
            strokeDasharray="2 6"
            strokeOpacity={0.7}
            label={{
              value: "25% safe line",
              position: "insideTopRight",
              fill: "var(--lime)",
              fontSize: 10,
            }}
          />
          <ReferenceLine
            x={quote}
            stroke={tone.stroke}
            strokeDasharray="4 4"
            label={{
              value: `quote ${fmtInt(quote)}d · ${Math.round(risk * 100)}%`,
              position: "insideTopLeft",
              fill: tone.stroke,
              fontSize: 10,
            }}
          />
          <Area
            type="monotone"
            dataKey="over_prob"
            name="P(overrun)"
            stroke="var(--cyan)"
            strokeWidth={2}
            fill="url(#pricingRiskFill)"
            dot={false}
          />
        </AreaChart>
      </ResponsiveContainer>

      <p className="text-[11px] leading-5 text-[var(--faint)]">
        Risk model: a{" "}
        <Term
          term="Lognormal pricing"
          tip="Overrun risk is a lognormal fit through the Full-scope P10/P50/P90 — the same shape the per-tier P(over budget) uses, so at the client's budget the numbers agree exactly. The shape is demo-assumed here; on real data it inherits the model's calibration (conformal intervals)."
        >
          lognormal fit
        </Term>{" "}
        through the Full-scope P10/P50/P90 — the same math as each tier&apos;s
        P(over budget), so at the client&apos;s budget the tier number and this
        curve agree. Demo-assumed shape; on real data it inherits the
        model&apos;s calibration.
      </p>
    </div>
  );
}
